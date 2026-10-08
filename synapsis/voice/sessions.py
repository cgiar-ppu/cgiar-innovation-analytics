"""Durable per-user Live leases, explicit uncertain outcomes and crash cleanup.

Uses the app's persisted SQLite database (and existing Litestream replication).
The container runs a reaper; heartbeat leases also recover abandoned tabs.
"""
import asyncio
import hashlib
import math
import os
import time
from urllib.parse import quote

import httpx
from fastapi import HTTPException
from synapsis.config import logger
from synapsis import ai_endpoint
from synapsis.database import get_db
from . import health
from .config import enabled, protocol, realtime_session_config, session_config

MAX_SECONDS = 600
HEARTBEAT_SECONDS = 60
# Columns added after the first release. init() adds any that are missing, so an
# older replicated database upgrades in place (SQLite ALTER TABLE ADD COLUMN only).
EXTRA_COLUMNS = {
    'closed': 'REAL',              # when the lease was confirmed closed
    'usage_seconds': 'REAL',       # server-observed lease duration: created -> closed
    'provider_seconds': 'REAL',    # provider-reported usage relayed by the browser on session.closed (client claim)
    'provider_status': 'INTEGER',  # HTTP status of the confirming hangup (200/404/410)
    'attempts': 'INTEGER NOT NULL DEFAULT 0',  # reaper hangup attempts for closing/uncertain leases
    'attempted': 'REAL NOT NULL DEFAULT 0',    # time of the last reaper hangup attempt (backoff anchor)
}
# Lease states. A lease leaves the owner's "one connection" rule only in a TERMINAL state.
TERMINAL = ('closed', 'rejected', 'closed_unconfirmed')
MAX_HANGUP_ATTEMPTS = 8            # 60 s, 120, 240, 480, then 600 s apart: ~45 min of retries
UNCONFIRMED_AFTER_SECONDS = 86400  # hard ceiling for a lease we could not confirm closed
# Review L6-08: after one provider failure (5xx/timeout on start) the owner used to be locked out
# of voice for 11 min (no provider ID) or ~45 min (hang-up retries). A create whose outcome is
# unknown and for which NO provider ID and NO SDP answer ever came back cannot have a connected
# media session (the browser never got the answer), so the owner is released after this short
# window. The daily/per-minute start caps are unchanged: every start still counts.
UNCERTAIN_NO_ID_RELEASE_SECONDS = 90
_reaper = None
_warmup = None
_creates: set[asyncio.Task] = set()


async def init():
    async with get_db() as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS voice_sessions (
            owner TEXT NOT NULL, request_id TEXT NOT NULL, sdp_hash TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL, provider_id TEXT, answer TEXT, created REAL NOT NULL,
            expires REAL NOT NULL, heartbeat REAL NOT NULL, PRIMARY KEY(owner, request_id))''')
        present = {row[1] for row in await (await db.execute('PRAGMA table_info(voice_sessions)')).fetchall()}
        for name, kind in EXTRA_COLUMNS.items():
            if name not in present:
                # Names come from the constant above, never from input.
                await db.execute(f'ALTER TABLE voice_sessions ADD COLUMN {name} {kind}')
        await db.execute('CREATE INDEX IF NOT EXISTS voice_session_status ON voice_sessions(status, expires)')
        await db.commit()


async def get(owner, request_id):
    async with get_db() as db:
        row = await (await db.execute('SELECT * FROM voice_sessions WHERE owner=? AND request_id=?', (owner, request_id))).fetchone()
        return dict(row) if row else None


async def update(owner, request_id, **values):
    # Column names are internal constants, never request/model parameters.
    async with get_db() as db:
        await db.execute('UPDATE voice_sessions SET ' + ','.join(k + '=?' for k in values) + ' WHERE owner=? AND request_id=?', (*values.values(), owner, request_id))
        await db.commit()


async def provider(path, body=None):
    """Live protocol call on the configured endpoint (Azure /openai/v1/live/..., or OpenAI /v1/live/...)."""
    async with httpx.AsyncClient(timeout=25 if path == 'sessions' else 8) as client:
        return await client.post(ai_endpoint.v1('live/' + path), headers=ai_endpoint.auth_headers(), json=body or {})


class _Answer:
    """Normalised provider outcome so _finish_create handles both protocols identically."""
    def __init__(self, status_code, data=None):
        self.status_code = status_code
        self.is_success = 200 <= status_code < 300
        self._data = data or {}

    def json(self):
        return self._data


async def _realtime_create(sdp):
    """GA Realtime over WebRTC, negotiated server-side so neither the key nor the ephemeral secret reaches
    the browser: mint a client secret carrying the session config, then exchange the SDP with it.
    The call ID comes back in the Location header (``/v1/realtime/calls/rtc_...``)."""
    async with httpx.AsyncClient(timeout=25) as client:
        minted = await client.post(ai_endpoint.v1('realtime/client_secrets'), headers=ai_endpoint.auth_headers(),
                                   json={'session': realtime_session_config()})
        if not minted.is_success:
            return _Answer(minted.status_code)
        secret = minted.json().get('value') or ''
        if not secret:
            raise ValueError('client secret missing')
        call = await client.post(ai_endpoint.v1('realtime/calls'), content=sdp.encode(),
                                 headers={'Authorization': 'Bearer ' + secret, 'Content-Type': 'application/sdp'})
        del secret
        if not call.is_success:
            return _Answer(call.status_code)
        call_id = call.headers.get('location', '').rstrip('/').rsplit('/', 1)[-1]
        return _Answer(call.status_code, {'session': {'id': call_id or None}, 'transport': {'sdp': call.text}})


async def _provider_create(sdp):
    if protocol() == 'realtime':
        return await _realtime_create(sdp)
    return await provider('sessions', {'session': session_config(), 'transport': {'type': 'webrtc', 'sdp': sdp}})


async def _provider_hangup(provider_id):
    if protocol() == 'realtime' or provider_id.startswith('rtc_'):
        async with httpx.AsyncClient(timeout=8) as client:
            return await client.post(ai_endpoint.v1('realtime/calls/' + quote(provider_id, safe='') + '/hangup'), headers=ai_endpoint.auth_headers())
    return await provider('sessions/' + quote(provider_id, safe='') + '/hangup')


async def _record_closed(row, provider_status, provider_seconds=None):
    """Mark a lease closed with the usage evidence we have and emit one CloudWatch-friendly line."""
    now = time.time()
    seconds = max(0.0, now - row['created'])
    await update(row['owner'], row['request_id'], status='closed', answer=None, closed=now, usage_seconds=seconds,
                 provider_seconds=provider_seconds, provider_status=provider_status)
    logger.info('voice_session_closed owner=%s request_id=%s seconds=%.0f provider_seconds=%s provider_status=%s',
                row['owner'], row['request_id'], seconds, 'null' if provider_seconds is None else f'{provider_seconds:.0f}', provider_status)


async def _hangup(row):
    """Ask the provider to end a known session. Returns (confirmed, http_status); never raises."""
    try:
        response = await _provider_hangup(row['provider_id'])
        if response.is_success or response.status_code in (404, 410):
            return True, response.status_code
        logger.warning('voice_hangup_unconfirmed owner=%s request_id=%s provider_status=%s', row['owner'], row['request_id'], response.status_code)
        return False, response.status_code
    except httpx.HTTPError as exc:
        logger.warning('voice_hangup_unconfirmed owner=%s request_id=%s error=%s', row['owner'], row['request_id'], type(exc).__name__)
        return False, None


async def close(owner, request_id, provider_seconds=None):
    # Tombstone wins even when End arrives before create or while upstream is pending.
    async with get_db() as db:
        await db.execute('BEGIN IMMEDIATE')
        await db.execute("INSERT OR IGNORE INTO voice_sessions(owner,request_id,status,created,expires,heartbeat) VALUES (?,?,'closed',?,?,?)", (owner, request_id, time.time(), time.time(), time.time()))
        row = dict(await (await db.execute('SELECT * FROM voice_sessions WHERE owner=? AND request_id=?', (owner, request_id))).fetchone())
        if row['status'] in TERMINAL:
            if row['status'] == 'closed' and provider_seconds is not None and row.get('provider_seconds') is None and row['sdp_hash']:
                # The reaper or a second tab already closed it; keep the provider's usage figure.
                await db.execute('UPDATE voice_sessions SET provider_seconds=? WHERE owner=? AND request_id=?', (provider_seconds, owner, request_id))
            await db.commit()
            return {'closed': True}
        await db.execute("UPDATE voice_sessions SET status='closing' WHERE owner=? AND request_id=?", (owner, request_id))
        await db.commit()
    if not row['provider_id']:
        return {'closed': False, 'status': 'awaiting_provider_reconciliation'}
    confirmed, status = await _hangup(row)
    if confirmed:
        await _record_closed(row, status, provider_seconds)
        return {'closed': True}
    return {'closed': False, 'status': 'cleanup_pending'}


async def create(owner, request_id, sdp):
    now = time.time()
    digest = hashlib.sha256(sdp.encode()).hexdigest()
    async with get_db() as db:
        await db.execute('BEGIN IMMEDIATE')
        old = await (await db.execute('SELECT * FROM voice_sessions WHERE owner=? AND request_id=?', (owner, request_id))).fetchone()
        if old:
            if old['sdp_hash'] == digest and old['status'] == 'active' and old['expires'] > now and old['heartbeat'] > now:
                return view(dict(old))
            raise HTTPException(409, 'This connection request is already used or awaiting cleanup. Do not automatically retry.')
        # One lease per owner until it is terminal: an uncertain outcome still blocks ITS owner (a paid
        # session may exist), but only leases that can really hold a provider session count against the
        # shared capacity: creating/active, and closing ones whose provider ID we know. 'uncertain' rows
        # and closing rows without a provider ID are bounded by the reaper (see reap_once) and must not
        # shrink the pool for everyone else while they wait.
        pending = await (await db.execute("SELECT status, provider_id, created FROM voice_sessions WHERE owner=? AND status NOT IN ('closed','rejected','closed_unconfirmed')", (owner,))).fetchall()
        wait = max((owner_block_seconds(dict(r), now) for r in pending), default=0)
        if wait > 0:
            raise HTTPException(409, 'Your previous voice connection is active or awaiting cleanup. '
                                     + ('End it before starting another.' if wait == float('inf')
                                        else f'Try again in about {_wait_phrase(wait)}.'))
        counted = (await (await db.execute("SELECT COUNT(*) FROM voice_sessions WHERE status IN ('creating','active') OR (status='closing' AND provider_id IS NOT NULL)")).fetchone())[0]
        if counted >= 6:
            raise HTTPException(429, 'All voice connections are currently in use. Try again in a few minutes.')
        counts = await (await db.execute('SELECT COUNT(*), SUM(owner=?) FROM voice_sessions WHERE created>? AND sdp_hash != \'\'', (owner, now - 86400))).fetchone()
        recent = await (await db.execute('SELECT COUNT(*) FROM voice_sessions WHERE owner=? AND created>?', (owner, now - 60))).fetchone()
        if counts[0] >= 100 or (counts[1] or 0) >= 20 or recent[0] >= 4:
            raise HTTPException(429, 'The voice start limit has been reached for now. Try again later.')
        await db.execute("INSERT INTO voice_sessions(owner,request_id,sdp_hash,status,provider_id,answer,created,expires,heartbeat) VALUES (?,?,?,'creating',NULL,NULL,?,?,?)",
                         (owner, request_id, digest, now, now + MAX_SECONDS, now + HEARTBEAT_SECONDS))
        await db.commit()
    # Shield upstream completion from browser cancellation so the provider ID is
    # recorded and compensated rather than losing an active paid session.
    task = asyncio.create_task(_finish_create(owner, request_id, sdp))
    _creates.add(task)
    task.add_done_callback(_creates.discard)
    return await asyncio.shield(task)


def owner_block_seconds(row, now):
    """How long a non-terminal lease still blocks its owner from starting voice (0 = not at all).

    * creating/active: until it ends (bounded by the heartbeat/expiry reaper) → ``inf``;
    * uncertain/closing with NO provider ID: no media session can exist (no SDP answer ever
      reached the browser) → released UNCERTAIN_NO_ID_RELEASE_SECONDS after the start;
    * uncertain/closing WITH a provider ID: a connected call cannot outlive the 10-minute limit
      (the browser ends it at expiry), so the owner is free after MAX_SECONDS + HEARTBEAT_SECONDS
      even while the reaper keeps retrying the hang-up in the background.
    """
    if row['status'] in ('creating', 'active'):
        return float('inf')
    window = MAX_SECONDS + HEARTBEAT_SECONDS if row['provider_id'] else UNCERTAIN_NO_ID_RELEASE_SECONDS
    return max(0.0, row['created'] + window - now)


def _wait_phrase(seconds):
    minutes = max(1, math.ceil(seconds / 60))
    return '1 minute' if minutes == 1 else f'{minutes} minutes'


def provider_error(status: int) -> str:
    """Operator-readable, user-safe explanation of a provider HTTP status. Never echoes the provider body."""
    hints = {401: 'check the API key', 403: 'the API key is not allowed to use this model',
             404: 'the configured voice model is not available to this key', 429: 'provider quota or rate limit reached'}
    hint = hints.get(status) or ('provider-side error' if status >= 500 else 'request rejected by the provider')
    return f'The voice provider rejected the request (HTTP {status} — {hint}); no automatic retry was made.'


async def _finish_create(owner, request_id, sdp):
    try:
        response = await _provider_create(sdp)
        if not response.is_success:
            # 5xx outcomes may be uncertain. Never release those leases blindly.
            await update(owner, request_id, status='uncertain' if response.status_code >= 500 else 'rejected')
            logger.warning('voice_create_rejected owner=%s request_id=%s provider_status=%s', owner, request_id, response.status_code)
            if response.status_code in (401, 403):
                health.invalidate()  # let the next /status re-probe so the UI disables voice promptly
            raise HTTPException(502 if response.status_code >= 500 else 503, provider_error(response.status_code))
        data = response.json()
        provider_id = data.get('session', {}).get('id')
        answer = data.get('transport', {}).get('sdp')
        if provider_id:
            await update(owner, request_id, provider_id=provider_id)
        if not provider_id or not answer:
            await update(owner, request_id, status='uncertain')
            if provider_id:
                await close(owner, request_id)
            raise HTTPException(502, 'Voice returned an incomplete connection; cleanup is pending.')
        async with get_db() as db:
            await db.execute("UPDATE voice_sessions SET status='active',answer=? WHERE owner=? AND request_id=? AND status='creating' AND heartbeat>?", (answer, owner, request_id, time.time()))
            await db.commit()
        row = await get(owner, request_id)
        if row['status'] != 'active':
            await close(owner, request_id)
            raise HTTPException(409, 'This voice start was cancelled or expired.')
        logger.info('voice_session_started owner=%s request_id=%s provider_id=%s', owner, request_id, provider_id)
        return view(row)
    except (httpx.HTTPError, ValueError):
        await update(owner, request_id, status='uncertain')
        raise HTTPException(502, 'Voice creation could not be confirmed. The request is retained for reconciliation; do not retry automatically.') from None


def view(row):
    return {'request_id': row['request_id'], 'transport': {'type': 'webrtc', 'sdp': row['answer']},
            'expires_at': row['expires'], 'max_seconds': MAX_SECONDS}


async def heartbeat(owner, request_id):
    async with get_db() as db:
        result = await db.execute("UPDATE voice_sessions SET heartbeat=? WHERE owner=? AND request_id=? AND status='active' AND expires>? AND heartbeat>?", (time.time() + HEARTBEAT_SECONDS, owner, request_id, time.time(), time.time()))
        await db.commit()
        if result.rowcount != 1:
            raise HTTPException(409, 'Voice connection expired or is closing.')
    return {'ok': True}


async def usage_today():
    """Rolling 24 h total of closed sessions; provider-reported seconds win over the server-observed duration."""
    async with get_db() as db:
        row = await (await db.execute("SELECT COUNT(*), COALESCE(SUM(COALESCE(provider_seconds, usage_seconds)), 0) FROM voice_sessions WHERE status='closed' AND sdp_hash != '' AND closed>?", (time.time() - 86400,))).fetchone()
    return {'sessions': row[0], 'seconds': round(row[1])}


def _backoff(attempts):
    return 0 if attempts == 0 else min(600, 60 * 2 ** (attempts - 1))


async def _give_up(row, now, reason):
    """Stop retrying but keep the row: an operator can still reconcile it against provider records."""
    await update(row['owner'], row['request_id'], status='closed_unconfirmed', closed=now, answer=None)
    logger.warning('voice_lease_unconfirmed owner=%s request_id=%s provider_id=%s attempts=%s age_seconds=%.0f reason=%s',
                   row['owner'], row['request_id'], row['provider_id'], row['attempts'], now - row['created'], reason)


async def _resolve_unconfirmed(row, now):
    """Bounded resolution of 'closing' and 'uncertain' leases.

    We never release a lease just because the provider answered 5xx or timed out: a paid session may
    exist. But "never" cannot mean "forever" — before this, one provider hiccup per owner would hold
    a slot in the six-connection pool until someone edited the database. So:
    - provider ID known: retry the hangup with backoff (60 s doubling to 600 s); after
      MAX_HANGUP_ATTEMPTS or UNCONFIRMED_AFTER_SECONDS mark it closed_unconfirmed and log the IDs
      an operator needs to reconcile against provider records.
    - no provider ID: nothing can be hung up. The SDP answer never reached the browser, so no media
      session was ever connected; a provider-side session created for that offer idles out on its
      own. After UNCERTAIN_NO_ID_RELEASE_SECONDS (was: the full call length + heartbeat, 11 min —
      review L6-08) the row is marked closed_unconfirmed and its owner may start again.
    """
    if row['provider_id']:
        if row['attempts'] >= MAX_HANGUP_ATTEMPTS or now - row['created'] > UNCONFIRMED_AFTER_SECONDS:
            return await _give_up(row, now, 'hangup_attempts_exhausted')
        if row['attempted'] and now < row['attempted'] + _backoff(row['attempts']):
            return
        await update(row['owner'], row['request_id'], attempts=row['attempts'] + 1, attempted=now)
        confirmed, status = await _hangup(row)
        if confirmed:
            await _record_closed(row, status)
    elif now - row['created'] > UNCERTAIN_NO_ID_RELEASE_SECONDS:
        await _give_up(row, now, 'no_provider_id_no_answer_delivered')


async def reap_once():
    now = time.time()
    async with get_db() as db:
        rows = await (await db.execute("SELECT * FROM voice_sessions WHERE status NOT IN ('closed','rejected','closed_unconfirmed') AND (expires<? OR heartbeat<? OR status IN ('closing','uncertain'))", (now, now))).fetchall()
    for row in rows:
        row = dict(row)
        if row['status'] in ('creating', 'active'):
            # Expired or heartbeat lost. A known provider session is ended; an unanswered create is
            # now of unknown outcome and handed to the bounded resolver on the next pass.
            if row['provider_id']:
                await close(row['owner'], row['request_id'])
            else:
                await update(row['owner'], row['request_id'], status='uncertain')
        else:
            await _resolve_unconfirmed(row, now)
    # Bounded metadata retention. Unresolved leases are never deleted; closed_unconfirmed rows are
    # kept for 30 days so an operator can reconcile them against provider records.
    async with get_db() as db:
        await db.execute("DELETE FROM voice_sessions WHERE status IN ('closed','rejected') AND created<?", (now - 7 * 86400,))
        await db.execute("DELETE FROM voice_sessions WHERE status='closed_unconfirmed' AND created<?", (now - 30 * 86400,))
        await db.commit()


async def run_reaper():
    while True:
        try:
            await reap_once()
        except Exception:
            logger.exception('Voice lease cleanup failed')
        await asyncio.sleep(10)


async def startup():
    global _reaper, _warmup
    await init()
    _reaper = asyncio.create_task(run_reaper())
    if enabled() and health.configured():
        # Warm the provider probe in the background so the first user gets an instant answer and every
        # container start leaves a voice_provider_probe_ok/failed line in the log group (deploy evidence).
        _warmup = asyncio.create_task(health.provider_ok())


async def shutdown():
    if _reaper:
        _reaper.cancel()
        await asyncio.gather(_reaper, return_exceptions=True)
    if _warmup:
        _warmup.cancel()
        await asyncio.gather(_warmup, return_exceptions=True)
    if _creates:
        await asyncio.gather(*_creates, return_exceptions=True)
    async with get_db() as db:
        rows = await (await db.execute("SELECT owner,request_id FROM voice_sessions WHERE status NOT IN ('closed','rejected','closed_unconfirmed')")).fetchall()
    await asyncio.gather(*(close(r['owner'], r['request_id']) for r in rows), return_exceptions=True)
