"""DEV QA smoke: the authenticated regression gate that runs after every DEV deploy.

WHERE IT RUNS
  * DEV: inside the container, after the "Live Opus 5.5 check" step of
    .github/workflows/deploy.yml (zlib+base64 exec'd via SSM ``docker exec``,
    mechanism A in the finalisation discovery D3 section 3).
  * Locally: against a local server that shares this process's environment
    (same IA_JWT_SECRET / SYNAPSIS_WORKSPACE / PRMS_DB_PATH):
        python .github/scripts/dev-qa-smoke.py --base-url http://localhost:7780

HOW IT AUTHENTICATES
  Synthetic identities minted in-process with the app's own JWT secret
  (``create_access_token``), exactly like release-smoke.py. Tokens are never
  printed; every string that leaves this script goes through ``scrub()``.

COST
  No model turn at all ($0.00). The only paid turn of a DEV deploy is the Opus
  5.5 check that runs just before; this script REUSES that turn (exports its
  answer and checks the usage ledger recorded it) instead of adding turns.

WHAT IT CHECKS (one JSON line on stdout; exit 1 if any check FAILS)
  ws_surface        every WebSocket route (walked through included routers) rejects
                    anonymous handshakes; the removed Synapsis sockets do not upgrade
  ws_chat_auth      /ws/chat: anonymous and forged tokens refused, researcher accepted
  privacy           researcher B gets 404 on researcher A's chat history and export
  model_policy      researcher /api/config model list == researcher policy; admin
                    list is a superset; switch_model to an admin-only model refused
                    with model_not_allowed and the socket stays usable
  rate_limit        the per-user new-chat limit answers rate_limited and keeps the socket
  admin_usage       /api/admin/usage 401 anonymous / 403 researcher / 200 admin
  removed_routes    Synapsis leftover routers answer 404 even for an admin
  security_headers  HSTS, nosniff, X-Frame-Options, Referrer-Policy, frame-ancestors, CSP
  citation_mapping  result code -> public PRMS report URL pattern for 2 known codes
  personas          the persona picker lists the two audience personas first
  prms_stats        the dashboard API answers with no KPI errors and consistent totals
  exports           md/html/docx of a seeded answer: 200, watermark, snapshot data-as-of
                    date, every seeded result code a link, owner-only
  exports_rendered  [Lane C] tables/bold/links rendered in HTML and DOCX, no '**',
                    no 'file://', legacy bare codes linked at export time
  ui_config         [Lane E] anonymous /api/health hides the model list, /api/config
                    serves contacts and drops leftovers, /api/activity needs a login
  feedback          [Lane H] owner-only answer feedback, admin list + CSV, 404 for others
  cohort_invites    [Lane H] bulk cohort invitation + cohort revoke (links never printed)
  real_turn         the Opus 5.5 check's own answer exports, and the usage ledger has it

  [Lane X] checks detect whether that lane's feature is deployed and are SKIPPED
  (with the reason) when it is not. Set IA_QA_REQUIRE=C,E,H (comma list) to turn
  those skips into failures once the lanes are merged.

CLEAN-UP
  Every chat it creates is titled "[QA] ..." and deleted at the end (also the Opus
  check's synthetic chat, unless IA_QA_KEEP_OPUS_SESSION=1); feedback is withdrawn;
  QA invitations are revoked.
"""
import asyncio
import datetime as _dt
import io
import json
import os
import re
import sys
import time
import traceback
import zipfile

import httpx
import websockets
from websockets.exceptions import ConnectionClosed, InvalidHandshake

BASE = 'http://localhost:7780'
REQUIRE = {x.strip().upper() for x in os.environ.get('IA_QA_REQUIRE', '').split(',') if x.strip()}
KNOWN_CODES = {'1003': 'result-details', '11855': 'ipsr-details'}   # public-report pattern per code
FIXTURE_CODES = ('1003', '14935')                                  # linked at "save" time
LEGACY_BARE_CODE = '11855'                                          # left bare: linked at export (Lane C)
REMOVED_ROUTES = ('/api/memories', '/api/workflows', '/api/workflow-runs', '/api/fleet', '/api/git/status',
                  '/api/skills', '/api/images/models', '/api/dashboard/stats', '/api/agent-query')
LANE_C_MARKER = 'synapsis.exporters.render'
REMOVED_SOCKETS = ('/ws/agent/qa-probe', '/ws/workflow/qa-probe', '/ws/fleet/qa-probe')
_SECRET_RE = [(re.compile(r'(token=)[^&\s\'"]+'), r'\1[REDACTED]'),
              (re.compile(r'eyJ[\w-]+\.[\w-]+\.[\w-]+'), '[JWT]'),
              (re.compile(r'(#invite=)[^&\s\'"]+'), r'\1[REDACTED]'),
              (re.compile(r'(Bearer )[\w.-]+'), r'\1[REDACTED]')]


def scrub(text) -> str:
    text = str(text)
    for rx, repl in _SECRET_RE:
        text = rx.sub(repl, text)
    return text


def quiet_logs():
    """httpx logs every request URL at INFO -- export URLs carry ``?token=``. Silence
    the HTTP client loggers and scrub anything else that reaches a log handler."""
    import logging

    class _Scrub(logging.Filter):
        def filter(self, record):
            record.msg, record.args = scrub(record.getMessage()), ()
            return True

    for name in ('httpx', 'httpcore', 'websockets', 'websockets.client'):
        logging.getLogger(name).setLevel(logging.WARNING)
    for handler in logging.getLogger().handlers:
        handler.addFilter(_Scrub())


class Skip(Exception):
    def __init__(self, reason, lane=None):
        super().__init__(reason)
        self.lane = lane


def iter_routes(routes, prefix=''):
    """(full_path, route) for every route, descending into included routers
    (FastAPI 0.141 keeps them as lazy entries whose own path is '')."""
    for r in routes:
        ctx, inner = getattr(r, 'include_context', None), getattr(r, 'original_router', None)
        if ctx is not None and inner is not None:
            yield from iter_routes(inner.routes, prefix + (ctx.prefix or ''))
        else:
            yield prefix + getattr(r, 'path', ''), r


def websocket_paths(app) -> list:
    from starlette.routing import WebSocketRoute
    from fastapi.routing import APIWebSocketRoute
    return sorted({p for p, r in iter_routes(app.routes) if isinstance(r, (WebSocketRoute, APIWebSocketRoute))})


def concrete(path: str) -> str:
    return re.sub(r'\{[^}]+\}', 'qa-probe', path)


async def ws_refused(url: str) -> str:
    """'refused <status>' / 'closed <code>' when the server rejects the handshake;
    raises AssertionError if the socket opens and stays open."""
    try:
        async with websockets.connect(url, open_timeout=15) as ws:
            try:
                await asyncio.wait_for(ws.recv(), 3)
            except ConnectionClosed as e:
                code = e.rcvd.code if e.rcvd else None
                assert code in (1008, 1003, 4401, 4403), ('socket accepted then closed with', code)
                return f'closed {code}'
            except asyncio.TimeoutError:
                pass
            raise AssertionError('WebSocket accepted an unauthenticated/invalid handshake')
    except InvalidHandshake as e:
        status = getattr(getattr(e, 'response', None), 'status_code', None)
        assert status is None or status >= 400, ('unexpected handshake status', status)
        return f'refused {status}'


class Chat:
    """A /ws/chat connection that ignores broadcast frames it did not ask for."""

    def __init__(self, ws):
        self.ws = ws

    async def ask(self, frame: dict, kinds: set, timeout: float = 60) -> dict:
        await self.ws.send(json.dumps(frame))
        async with asyncio.timeout(timeout):
            while True:
                e = json.loads(await self.ws.recv())
                if e.get('type') in kinds or e.get('type') == 'error':
                    return e


class QA:
    def __init__(self, base: str):
        self.base = base.rstrip('/')
        self.ws_base = self.base.replace('http', 'ws', 1)
        self.results = []
        self.cleanup_sessions = []   # (session_id, owner_token)
        self.cleanup_feedback = []   # (feedback_id, owner_token)
        self.cleanup_cohorts = []
        self.http = None

    # ------------------------------------------------------------------ plumbing
    async def run(self, name, fn):
        t0 = time.monotonic()
        try:
            detail = await fn()
            self.results.append({'check': name, 'status': 'pass', 'detail': scrub(detail)})
        except Skip as s:
            status = 'fail' if s.lane and s.lane in REQUIRE else 'skip'
            self.results.append({'check': name, 'status': status, 'detail': scrub(str(s)),
                                 **({'lane': s.lane} if s.lane else {})})
        except Exception as e:  # noqa: BLE001 -- every failure is reported, never raised
            msg = e.args[0] if isinstance(e, AssertionError) and e.args else f'{type(e).__name__}: {e}'
            self.results.append({'check': name, 'status': 'fail', 'detail': scrub(msg)})
        self.results[-1]['seconds'] = round(time.monotonic() - t0, 2)

    def h(self, token=None, **extra):
        return {**({'Authorization': 'Bearer ' + token} if token else {}), **extra}

    async def get(self, path, token=None, **kw):
        return await self.http.get(self.base + path, headers=self.h(token, **kw.pop('headers', {})), **kw)

    def connect(self, token=None, query=None):
        q = query if query is not None else (('?token=' + token) if token else '')
        return websockets.connect(self.ws_base + '/ws/chat' + q, open_timeout=30, max_size=8 * 1024 * 1024)

    # ------------------------------------------------------------------ identities + fixtures
    def mint(self):
        from synapsis import config
        from synapsis.auth.tokens import create_access_token
        source = 'sso' if config.SSO_ENABLED else 'password'
        self.run_id = 'dev-qa-' + str(int(time.time()))
        ids = {'admin': (self.run_id + '-admin', 'admin'), 'a': (self.run_id + '-a', 'researcher'),
               'b': (self.run_id + '-b', 'researcher'), 'c': (self.run_id + '-c', 'researcher')}
        self.uid = {k: v[0] for k, v in ids.items()}
        self.tok = {k: create_access_token(uid, 'DEV QA synthetic ' + k, role, auth_source=source,
                                           lifetime_seconds=900) for k, (uid, role) in ids.items()}

    async def seed_chat(self, owner_key: str, title: str, messages: list) -> str:
        from synapsis import config
        from synapsis.database.connection import get_db
        sid = f'{self.run_id}-{owner_key}-{len(self.cleanup_sessions)}'
        now = time.time()
        async with get_db() as db:
            await db.execute('INSERT INTO sessions(session_id,title,created_at,updated_at,model,user_id) '
                             'VALUES(?,?,?,?,?,?)', (sid, '[QA] ' + title, now, now, config.MODEL, self.uid[owner_key]))
            for i, (kind, data) in enumerate(messages):
                await db.execute('INSERT INTO messages(session_id,type,data,ts) VALUES(?,?,?,?)',
                                 (sid, kind, json.dumps(data), now + i * 0.01))
            await db.commit()
        self.cleanup_sessions.append((sid, self.tok[owner_key]))
        return sid

    def fixture_markdown(self):
        from synapsis.tools.result_code_citation import linkify_result_codes
        table = ('| QA-Col-Alpha | QA-Col-Beta |\n|---|---|\n'
                 + ''.join(f'| [R{c}] | {n} |\n' for c, n in zip(FIXTURE_CODES, (12, 7))))
        saved = linkify_result_codes(  # what the live handler persists (Lane G, message_handlers)
            'Synthetic DEV QA fixture, not a portfolio claim. **QA bold marker** and a '
            '[QA public link](https://www.cgiar.org/).\n\n' + table + '\nSources: '
            + ', '.join(f'[R{c}]' for c in FIXTURE_CODES))
        legacy = f'Answer saved before the linkifier existed cites [R{LEGACY_BARE_CODE}] bare.'
        return saved, legacy

    # ------------------------------------------------------------------ checks
    async def c_ws_surface(self):
        from synapsis.server import app
        paths = websocket_paths(app)
        assert paths, 'route walker found no WebSocket route (walker blind?)'
        out = {}
        for p in paths:
            out[p] = await ws_refused(self.ws_base + concrete(p))
        for p in REMOVED_SOCKETS:
            out[p] = await ws_refused(self.ws_base + p)
        unexpected = [p for p in paths if p != '/ws/chat']
        assert not unexpected, ('unexpected WebSocket routes', unexpected, out)
        return {'websocket_routes': paths, 'anonymous': out}

    async def c_ws_chat_auth(self):
        forged = await ws_refused(self.ws_base + '/ws/chat?token=forged.not.a.jwt')
        async with self.connect(self.tok['a']) as ws:
            e = await Chat(ws).ask({'type': 'new_session'}, {'session'})
            assert e.get('type') == 'session' and e.get('session_id'), ('researcher new_session', e.get('code'))
            self.ws_session_a = e['session_id']
        self.cleanup_sessions.append((self.ws_session_a, self.tok['a']))
        r = await self.http.patch(self.base + '/api/sessions/' + self.ws_session_a, headers=self.h(self.tok['a']),
                                  json={'title': '[QA] DEV QA socket session'})
        assert r.status_code == 200, ('title PATCH', r.status_code)
        return {'anonymous': 'refused (see ws_surface)', 'forged_token': forged, 'researcher': 'accepted'}

    async def c_privacy(self):
        sid = self.ws_session_a
        assert (await self.get('/api/history/' + sid, self.tok['a'])).status_code == 200
        assert (await self.get('/api/history/' + sid, self.tok['b'])).status_code == 404, 'B read A history'
        assert (await self.get('/api/export/' + self.export_sid, params={'token': self.tok['b']})).status_code == 404, \
            'B exported A chat'
        r = await self.http.delete(self.base + '/api/sessions/' + sid, headers=self.h(self.tok['b']))
        assert r.status_code in (403, 404), ('B deleted A chat', r.status_code)
        return 'researcher B: history 404, export 404, delete refused'

    async def c_model_policy(self):
        r_cfg = (await self.get('/api/config', self.tok['a'])).json()
        a_cfg = (await self.get('/api/config', self.tok['admin'])).json()
        rp, ap = r_cfg.get('model_policy') or {}, a_cfg.get('model_policy') or {}
        r_ids = [m['id'] for m in r_cfg.get('selectable_models', [])]
        a_ids = [m['id'] for m in a_cfg.get('selectable_models', [])]
        assert rp.get('role') == 'researcher' and ap.get('role') == 'admin', (rp.get('role'), ap.get('role'))
        assert set(r_ids) == set(rp.get('allowed_models', [])), ('researcher list != policy', r_ids, rp.get('allowed_models'))
        assert set(r_ids) <= set(a_ids), ('researcher offered a model admins are not', r_ids, a_ids)
        assert rp.get('show_cost') is False and ap.get('show_cost') is True, 'show_cost by role'
        admin_only = [m for m in a_ids if m not in r_ids]
        detail = {'researcher_models': r_ids, 'admin_models': a_ids,
                  'researcher_budget_per_turn': rp.get('max_budget_usd_per_turn'),
                  'researcher_daily_budget': rp.get('daily_budget_usd'), 'max_turns': rp.get('max_turns')}
        if not admin_only:
            detail['switch_model'] = 'skipped: no admin-only model in this environment'
            return detail
        async with self.connect(self.tok['a']) as ws:
            chat = Chat(ws)
            e = await chat.ask({'type': 'switch_session', 'session_id': self.ws_session_a}, {'session'})
            assert e.get('type') == 'session', ('switch_session', e.get('code'))
            e = await chat.ask({'type': 'switch_model', 'model': admin_only[0]}, {'model_switched'})
            assert e.get('type') == 'error' and e.get('code') == 'model_not_allowed', \
                ('researcher switch to admin-only model was not refused', e.get('type'), e.get('code'))
            e = await chat.ask({'type': 'switch_session', 'session_id': self.ws_session_a}, {'session'})
            assert e.get('type') == 'session', 'socket unusable after the refusal'
        detail['switch_model'] = f'{admin_only[0]} refused (model_not_allowed), socket still usable'
        return detail

    async def c_rate_limit(self):
        from synapsis import config
        limit = int(getattr(config, 'NEW_CHATS_PER_USER', 5))
        kinds = []
        async with self.connect(self.tok['c']) as ws:
            chat = Chat(ws)
            for _ in range(limit + 1):
                e = await chat.ask({'type': 'new_session'}, {'session'})
                if e.get('type') == 'session':
                    self.cleanup_sessions.append((e['session_id'], self.tok['c']))
                    kinds.append('session')
                else:
                    kinds.append(e.get('code') or 'error')
            first = next((s for s, t in self.cleanup_sessions if t == self.tok['c']), None)
            e = await chat.ask({'type': 'switch_session', 'session_id': first}, {'session'})
            alive = e.get('type') == 'session'
        for sid, tok in self.cleanup_sessions:
            if tok == self.tok['c']:
                await self.http.patch(self.base + '/api/sessions/' + sid, headers=self.h(tok),
                                      json={'title': '[QA] DEV QA rate-limit probe'})
        assert kinds == ['session'] * limit + ['rate_limited'], ('new_session sequence', kinds)
        assert alive, 'socket did not survive the rate-limit refusal'
        return {'per_user_limit': limit, 'sequence': kinds, 'socket_after_refusal': 'alive'}

    async def c_admin_usage(self):
        codes = [(await self.get('/api/admin/usage?days=2', t)).status_code
                 for t in (None, self.tok['a'], self.tok['admin'])]
        assert codes == [401, 403, 200], ('anonymous/researcher/admin', codes)
        body = (await self.get('/api/admin/usage?days=2', self.tok['admin'])).json()
        assert isinstance(body.get('daily'), list) and body.get('environment'), 'usage payload shape'
        return {'status': codes, 'environment': body.get('environment')}

    async def c_removed_routes(self):
        bad = {}
        for p in REMOVED_ROUTES:
            r = await self.get(p, self.tok['admin'])
            if r.status_code != 404:
                bad[p] = r.status_code
        assert not bad, ('leftover routes still answer', bad)
        return f'{len(REMOVED_ROUTES)} leftover routes -> 404 (admin token)'

    async def c_security_headers(self):
        out = {}
        for p in ('/', '/api/health'):
            hd = (await self.get(p)).headers
            csp = hd.get('content-security-policy', '')
            missing = [k for k, ok in (
                ('strict-transport-security', 'max-age=' in hd.get('strict-transport-security', '')),
                ('x-content-type-options', hd.get('x-content-type-options') == 'nosniff'),
                ('x-frame-options', hd.get('x-frame-options', '').upper() == 'DENY'),
                ('referrer-policy', bool(hd.get('referrer-policy'))),
                ('frame-ancestors', "frame-ancestors 'none'" in csp),
                ('csp', bool(csp or hd.get('content-security-policy-report-only'))),
            ) if not ok]
            assert not missing, (p, 'missing security headers', missing)
            out[p] = 'report-only CSP' if hd.get('content-security-policy-report-only') else 'enforced CSP'
        return out

    async def c_citation_mapping(self):
        from synapsis.tools.result_code_citation import linkify_result_codes, resolve_result_code_url
        out = {}
        for code, kind in KNOWN_CODES.items():
            url = resolve_result_code_url(code) or ''
            assert re.fullmatch(rf'https://reporting\.cgiar\.org/reports/{kind}/{code}\?phase=\d+', url), (code, url)
            out[code] = url
        assert resolve_result_code_url('9999999') is None, 'unknown code resolved'
        assert 'not found in the PRMS snapshot' in linkify_result_codes('[R9999999]'), 'unknown code not flagged'
        return out

    async def c_personas(self):
        r = await self.get('/api/personas', self.tok['a'])
        assert r.status_code == 200, r.status_code
        ids = [p['id'] for p in r.json()['personas']]
        assert ids[:2] == ['funder_investor', 'scientist_researcher'], ids[:4]
        assert (await self.get('/api/personas')).status_code == 401, 'personas open to anonymous callers'
        return {'first': ids[:2], 'count': len(ids)}

    async def c_prms_stats(self):
        r = await self.get('/api/dashboard/prms-stats', self.tok['a'])
        assert r.status_code == 200, r.status_code
        body = r.json()
        k = body.get('kpis', {})
        assert not body.get('kpi_errors'), ('kpi_errors', body.get('kpi_errors'))
        assert (k.get('total_innovations') or 0) > 0, 'no innovations'
        if k.get('total_innovations_w1w2') is not None and k.get('total_innovations_bilateral') is not None:
            assert k['total_innovations'] == k['total_innovations_w1w2'] + k['total_innovations_bilateral'], k
        return {'total_innovations': k.get('total_innovations'), 'total_results': k.get('total_results'),
                'snapshot': (body.get('snapshot') or {}).get('extracted_on')}

    async def _export(self, fmt, sid=None, token=None):
        r = await self.http.get(self.base + '/api/export/' + (sid or self.export_sid),
                                params={'format': fmt, 'token': token or self.tok['a']})
        assert r.status_code == 200, (fmt, 'export status', r.status_code)
        if fmt == 'docx':
            z = zipfile.ZipFile(io.BytesIO(r.content))
            xml = {n: z.read(n).decode('utf-8', 'replace') for n in z.namelist() if n.endswith(('.xml', '.rels'))}
            doc = xml.get('word/document.xml', '')
            return {'text': re.sub(r'<[^>]+>', '', doc), 'doc': doc,
                    'all': '\n'.join(xml.values())}
        return {'text': r.text, 'doc': r.text, 'all': r.text}

    async def c_exports(self):
        from synapsis.exporters.watermark import WATERMARK_BANNER
        from synapsis.prms_snapshot import get_snapshot_info
        from synapsis.tools.result_code_citation import resolve_result_code_url
        info = get_snapshot_info()
        as_of = info.data_as_of or info.extracted_on
        urls = {c: resolve_result_code_url(c) for c in FIXTURE_CODES}
        self.exported = {}
        for fmt in ('md', 'html', 'docx'):
            ex = self.exported[fmt] = await self._export(fmt)
            assert WATERMARK_BANNER in ex['all'], (fmt, 'watermark banner missing')
            if as_of:
                assert as_of in ex['all'], (fmt, 'snapshot data-as-of date missing', as_of)
        missing = [c for c, u in urls.items() if not u or u not in self.exported['md']['text']]
        assert not missing, ('md export lost result-code links', missing)
        return {'formats': ['md', 'html', 'docx'], 'data_as_of': as_of, 'linked_codes': sorted(urls)}

    async def c_exports_rendered(self):
        import importlib.util
        if not getattr(self, 'exported', None):
            raise Skip('exports check did not produce the exports')
        # Feature marker: Lane C's shared renderer module (+ its markdown-it-py pin).
        if importlib.util.find_spec(LANE_C_MARKER) is None or importlib.util.find_spec('markdown_it') is None:
            raise Skip(f'Lane C Markdown renderer ({LANE_C_MARKER}) not deployed', 'C')
        from synapsis.tools.result_code_citation import resolve_result_code_url
        urls = {c: resolve_result_code_url(c) for c in {*FIXTURE_CODES, LEGACY_BARE_CODE}}
        html, docx, md = self.exported['html'], self.exported['docx'], self.exported['md']
        problems = []
        m = re.search(r'<table.*?</table>', html['doc'], re.S)
        if not (m and 'QA-Col-Alpha' in m.group(0)):
            problems.append('html: seeded table not rendered as <table>')
        if not re.search(r'<(strong|b)>QA bold marker</(strong|b)>', html['doc']):
            problems.append('html: bold not rendered')
        for c, u in urls.items():
            if f'href="{u}"' not in html['doc'] and f'href="{u.replace("&", "&amp;")}"' not in html['doc']:
                problems.append(f'html: R{c} not a link')
            if u not in docx['all']:
                problems.append(f'docx: R{c} hyperlink target missing')
            if u not in md['text']:
                problems.append(f'md: R{c} not linked')
        if '<w:hyperlink' not in docx['doc']:
            problems.append('docx: no hyperlinks')
        if not any('QA-Col-Alpha' in t for t in re.findall(r'<w:tbl>.*?</w:tbl>', docx['doc'], re.S)):
            problems.append('docx: seeded table not a Word table')
        for fmt, ex in (('html', html), ('docx', docx)):
            if '**' in ex['text']:
                problems.append(f'{fmt}: raw ** left')
        for fmt, ex in self.exported.items():
            if 'file://' in ex['all']:
                problems.append(f'{fmt}: file:// path leaked')
        today = _dt.date.today().isoformat()
        from synapsis.prms_snapshot import get_snapshot_info
        if today != get_snapshot_info().data_as_of and any(f'Data as of {today}' in e['all'] for e in self.exported.values()):
            problems.append('"Data as of <export date>" still printed')
        assert not problems, problems
        return 'html+docx: tables, bold, links rendered; no **, no file://; legacy bare code linked'

    async def c_ui_config(self):
        anon_cfg = (await self.get('/api/config')).json()
        if 'contacts' not in anon_cfg:
            raise Skip('Lane E /api/config contacts contract not deployed', 'E')
        problems = []
        if 'available_models' in (await self.get('/api/health')).json():
            problems.append('anonymous /api/health lists the models')
        if 'available_models' not in (await self.get('/api/health', self.tok['admin'])).json():
            problems.append('admin /api/health lost available_models')
        leftovers = [k for k in ('memory_categories', 'vnc_available', 'vnc_port') if k in anon_cfg]
        if leftovers:
            problems.append(f'/api/config leftovers {leftovers}')
        contacts = anon_cfg.get('contacts') or []
        if not contacts or not all('@' in (c.get('email') or '') for c in contacts):
            problems.append('contacts missing or without email')
        if (await self.get('/api/activity')).status_code != 401:
            problems.append('/api/activity open to anonymous callers')
        assert not problems, problems
        return {'contacts': [c.get('remit') for c in contacts], 'health_anonymous': 'no model list'}

    async def c_feedback(self):
        probe = await self.get('/api/admin/feedback?days=1', self.tok['admin'])
        if probe.status_code == 404:
            raise Skip('Lane H feedback endpoints not deployed (or IA_FEEDBACK_ENABLED=false)', 'H')
        assert probe.status_code == 200, ('admin list', probe.status_code)
        codes = [(await self.get('/api/admin/feedback', t)).status_code for t in (None, self.tok['a'])]
        assert codes == [401, 403], ('anonymous/researcher admin list', codes)
        body = {'channel': 'chat', 'session_id': self.export_sid, 'message_id': 'r1', 'rating': 1,
                'comment': '[QA] synthetic feedback'}
        r = await self.http.post(self.base + '/api/feedback', headers=self.h(self.tok['b']), json=body)
        assert r.status_code == 404, ('B rated A answer', r.status_code)
        r = await self.http.post(self.base + '/api/feedback', headers=self.h(self.tok['a']), json=body)
        assert r.status_code == 200, ('owner feedback', r.status_code)
        fid = r.json().get('id')
        if fid is not None:
            self.cleanup_feedback.append((fid, self.tok['a']))
        own = (await self.get('/api/feedback', self.tok['a'], params={'session_id': self.export_sid})).json()
        assert len(own.get('feedback', [])) == 1, 'own feedback not listed once'
        listed = (await self.get('/api/admin/feedback?days=1', self.tok['admin'])).json()
        assert any(i.get('session_id') == self.export_sid for i in listed.get('items', [])), 'admin list misses it'
        csv = await self.get('/api/admin/feedback?days=1&format=csv', self.tok['admin'])
        assert csv.status_code == 200 and 'text/csv' in csv.headers.get('content-type', ''), 'CSV export'
        return 'owner write 200, foreign write 404, admin list + CSV 200, 401/403 for others'

    async def c_cohort_invites(self):
        from synapsis import config
        if not config.INVITED_LOGIN_ENABLED:
            raise Skip('invited login disabled in this environment')
        origin = {'Origin': config.SSO_ORIGIN} if config.SSO_ORIGIN else {}
        cohort = 'QA ' + self.run_id
        r = await self.http.post(self.base + '/api/auth/invitations/bulk', headers=self.h(self.tok['admin'], **origin),
                                 json={'cohort': cohort, 'expires_in_days': 1,
                                       'invitees': [{'email': self.run_id + '@example.com',
                                                     'name': 'DEV QA synthetic (revoked by the smoke)'}]})
        if r.status_code in (404, 405):
            raise Skip('Lane H cohort invitations not deployed', 'H')
        assert r.status_code == 200, ('bulk invite', r.status_code)
        self.cleanup_cohorts.append((cohort, origin))
        links = [i.get('invitation_url', '') for i in r.json().get('invitations', [])]
        assert len(links) == 1 and '#invite=' in links[0], 'one fragment link expected'
        token = links[0].split('#invite=', 1)[1]
        rv = await self.http.post(self.base + '/api/auth/invitations/revoke-cohort',
                                  headers=self.h(self.tok['admin'], **origin), json={'cohort': cohort})
        assert rv.status_code == 200 and rv.json().get('revoked', 0) >= 1, ('revoke cohort', rv.status_code)
        self.cleanup_cohorts.pop()
        acc = await self.http.post(self.base + '/api/auth/invitation/accept', headers=origin,
                                   json={'token': token, 'password': 'QA-' + os.urandom(12).hex()})
        assert acc.status_code in (400, 401, 403, 404, 410), ('revoked link still activates', acc.status_code)
        return {'cohort_link': 'created (not printed)', 'revoke_cohort': rv.json().get('revoked'),
                'accept_after_revoke': acc.status_code}

    async def c_real_turn(self):
        """Reuse the deploy's Opus 5.5 check turn: export its answer, and check the ledger."""
        from synapsis.auth.tokens import create_access_token
        from synapsis.database.connection import get_db
        async with get_db() as db:
            cur = await db.execute("SELECT session_id, user_id FROM sessions WHERE title = ? AND updated_at > ? "
                                   "ORDER BY updated_at DESC LIMIT 1",
                                   ('[QA] Opus 5.5 DEV verification', time.time() - 3600))
            row = await cur.fetchone()
        if not row:
            raise Skip('no Opus 5.5 check chat from the last hour (the check did not run)')
        sid, owner = row[0], row[1]
        from synapsis import config
        tok = create_access_token(owner, 'DEV QA (Opus check owner)', 'admin',
                                  auth_source='sso' if config.SSO_ENABLED else 'password', lifetime_seconds=300)
        if os.environ.get('IA_QA_KEEP_OPUS_SESSION') != '1':
            self.cleanup_sessions.append((sid, tok))
        md = await self._export('md', sid, tok)
        assert '323' in md['text'], 'the Opus answer (323) is missing from its export'
        await self._export('docx', sid, tok)
        usage = (await self.get('/api/admin/usage?days=1', self.tok['admin'])).json()
        turns = (usage.get('totals') or {}).get('turns', 0)
        assert turns >= 1, 'usage ledger has no turn today although the Opus check ran'
        return {'opus_chat_export': 'md+docx ok', 'ledger_turns_today': turns,
                'ledger_cost_today_usd': (usage.get('totals') or {}).get('cost_usd')}

    # ------------------------------------------------------------------ cleanup
    async def cleanup(self):
        report = {'sessions_deleted': 0, 'sessions_left': [], 'feedback_withdrawn': 0, 'cohorts_revoked': 0}
        for fid, tok in self.cleanup_feedback:
            r = await self.http.delete(f'{self.base}/api/feedback/{fid}', headers=self.h(tok))
            report['feedback_withdrawn'] += r.status_code == 200
        for cohort, origin in self.cleanup_cohorts:
            r = await self.http.post(self.base + '/api/auth/invitations/revoke-cohort',
                                     headers=self.h(self.tok['admin'], **origin), json={'cohort': cohort})
            report['cohorts_revoked'] += r.status_code == 200
        for sid, tok in dict(self.cleanup_sessions).items():
            r = await self.http.delete(self.base + '/api/sessions/' + sid, headers=self.h(tok))
            if r.status_code == 200:
                report['sessions_deleted'] += 1
            else:
                report['sessions_left'].append(sid)
        return report


async def main(base: str) -> int:
    from synapsis.database.connection import close_db
    quiet_logs()
    qa = QA(base)
    qa.mint()
    started = time.time()
    async with httpx.AsyncClient(timeout=120) as http:
        qa.http = http
        saved, legacy = qa.fixture_markdown()
        qa.export_sid = await qa.seed_chat('a', 'DEV QA export fixture', [
            ('user', {'content': '[QA] synthetic question'}),
            ('text', {'content': saved}),
            ('text', {'content': legacy}),
            ('result', {'estimated_cost': 0, 'turns': 1, 'subtype': 'success'}),
        ])
        checks = [('ws_surface', qa.c_ws_surface), ('ws_chat_auth', qa.c_ws_chat_auth), ('privacy', qa.c_privacy),
                  ('model_policy', qa.c_model_policy), ('rate_limit', qa.c_rate_limit),
                  ('admin_usage', qa.c_admin_usage), ('removed_routes', qa.c_removed_routes),
                  ('security_headers', qa.c_security_headers), ('citation_mapping', qa.c_citation_mapping),
                  ('personas', qa.c_personas), ('prms_stats', qa.c_prms_stats), ('exports', qa.c_exports),
                  ('exports_rendered', qa.c_exports_rendered), ('ui_config', qa.c_ui_config),
                  ('feedback', qa.c_feedback), ('cohort_invites', qa.c_cohort_invites),
                  ('real_turn', qa.c_real_turn)]
        try:
            for name, fn in checks:
                if name == 'privacy' and not hasattr(qa, 'ws_session_a'):
                    qa.results.append({'check': name, 'status': 'fail', 'detail': 'no researcher chat (ws_chat_auth failed)'})
                    continue
                await qa.run(name, fn)
        finally:
            cleanup = await qa.cleanup()
    await close_db()
    counts = {s: sum(r['status'] == s for r in qa.results) for s in ('pass', 'fail', 'skip')}
    print(scrub(json.dumps({'dev_qa_smoke': {
        'run_id': qa.run_id, 'base_url': base, 'summary': counts, 'required_lanes': sorted(REQUIRE),
        'model_spend_usd': 0.0, 'seconds': round(time.time() - started, 1),
        'checks': qa.results, 'cleanup': cleanup}})))
    return 1 if counts['fail'] or cleanup['sessions_left'] else 0


def _entry():
    # Run as a file from a checkout: make the repo's ``synapsis`` importable. (In the
    # container the script is exec'd by ``python -c`` from /app, already on sys.path.)
    root = os.path.abspath(os.path.join(os.path.dirname(globals().get('__file__', '.')), '..', '..'))
    if '__file__' in globals() and os.path.isdir(os.path.join(root, 'synapsis')) and root not in sys.path:
        sys.path.insert(0, root)
    base = BASE
    if '--base-url' in sys.argv:
        base = sys.argv[sys.argv.index('--base-url') + 1]
    try:
        code = asyncio.run(main(base))
    except Exception:  # noqa: BLE001 -- print a scrubbed traceback, never a token
        print(scrub(json.dumps({'dev_qa_smoke': {'crashed': traceback.format_exc()[-3000:]}})))
        code = 1
    sys.stdout.flush()
    if code:
        raise SystemExit(code)


# deploy.yml exec()s this file inside `python -c`, where __name__ is '__main__';
# tests import it instead.
if __name__ == '__main__':
    _entry()
