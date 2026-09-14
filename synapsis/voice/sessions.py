"""Durable per-user Live leases, explicit uncertain outcomes and crash cleanup.

Uses the app's persisted SQLite database (and existing Litestream replication).
The container runs a reaper; heartbeat leases also recover abandoned tabs.
"""
import asyncio
import hashlib
import os
import time
from urllib.parse import quote

import httpx
from fastapi import HTTPException
from synapsis.config import logger
from synapsis.database import get_db
from . import health
from .config import session_config

MAX_SECONDS = 600
HEARTBEAT_SECONDS = 60
# Columns added after the first release. init() adds any that are missing, so an
# older replicated database upgrades in place (SQLite ALTER TABLE ADD COLUMN only).
EXTRA_COLUMNS = {
    'closed': 'REAL',              # when the lease was confirmed closed
    'usage_seconds': 'REAL',       # server-observed lease duration: created -> closed
    'provider_seconds': 'REAL',    # provider-reported usage relayed by the browser on session.closed (client claim)
    'provider_status': 'INTEGER',  # HTTP status of the confirming hangup (200/404/410)
}
_reaper = None
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
    async with httpx.AsyncClient(timeout=25 if path == 'sessions' else 8) as client:
        return await client.post('https://api.openai.com/v1/live/' + path,
                                 headers={'Authorization': 'Bearer ' + os.getenv('OPENAI_API_KEY', '')}, json=body or {})


async def _record_closed(row, provider_status, provider_seconds=None):
    """Mark a lease closed with the usage evidence we have and emit one CloudWatch-friendly line."""
    now = time.time()
    seconds = max(0.0, now - row['created'])
    await update(row['owner'], row['request_id'], status='closed', answer=None, closed=now, usage_seconds=seconds,
                 provider_seconds=provider_seconds, provider_status=provider_status)
    logger.info('voice_session_closed owner=%s request_id=%s seconds=%.0f provider_seconds=%s provider_status=%s',
                row['owner'], row['request_id'], seconds, 'null' if provider_seconds is None else f'{provider_seconds:.0f}', provider_status)


async def close(owner, request_id, provider_seconds=None):
    # Tombstone wins even when End arrives before create or while upstream is pending.
    async with get_db() as db:
        await db.execute('BEGIN IMMEDIATE')
        await db.execute("INSERT OR IGNORE INTO voice_sessions(owner,request_id,status,created,expires,heartbeat) VALUES (?,?,'closed',?,?,?)", (owner, request_id, time.time(), time.time(), time.time()))
        row = dict(await (await db.execute('SELECT * FROM voice_sessions WHERE owner=? AND request_id=?', (owner, request_id))).fetchone())
        if row['status'] in ('closed', 'rejected'):
            if row['status'] == 'closed' and provider_seconds is not None and row.get('provider_seconds') is None and row['sdp_hash']:
                # The reaper or a second tab already closed it; keep the provider's usage figure.
                await db.execute('UPDATE voice_sessions SET provider_seconds=? WHERE owner=? AND request_id=?', (provider_seconds, owner, request_id))
            await db.commit()
            return {'closed': True}
        await db.execute("UPDATE voice_sessions SET status='closing' WHERE owner=? AND request_id=?", (owner, request_id))
        await db.commit()
    if not row['provider_id']:
        return {'closed': False, 'status': 'awaiting_provider_reconciliation'}
    try:
        response = await provider('sessions/' + quote(row['provider_id'], safe='') + '/hangup')
        if response.is_success or response.status_code in (404, 410):
            await _record_closed(row, response.status_code, provider_seconds)
            return {'closed': True}
        logger.warning('voice_hangup_unconfirmed owner=%s request_id=%s provider_status=%s', owner, request_id, response.status_code)
    except httpx.HTTPError as exc:
        logger.warning('voice_hangup_unconfirmed owner=%s request_id=%s error=%s', owner, request_id, type(exc).__name__)
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
        active = await (await db.execute("SELECT owner FROM voice_sessions WHERE status NOT IN ('closed','rejected')")).fetchall()
        if any(row['owner'] == owner for row in active):
            raise HTTPException(409, 'Your previous voice connection is active or awaiting cleanup. End it before starting another.')
        if len(active) >= 6:
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


def provider_error(status: int) -> str:
    """Operator-readable, user-safe explanation of a provider HTTP status. Never echoes the provider body."""
    hints = {401: 'check the API key', 403: 'the API key is not allowed to use this model',
             404: 'the configured voice model is not available to this key', 429: 'provider quota or rate limit reached'}
    hint = hints.get(status) or ('provider-side error' if status >= 500 else 'request rejected by the provider')
    return f'The voice provider rejected the request (HTTP {status} — {hint}); no automatic retry was made.'


async def _finish_create(owner, request_id, sdp):
    try:
        response = await provider('sessions', {'session': session_config(), 'transport': {'type': 'webrtc', 'sdp': sdp}})
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


async def reap_once():
    async with get_db() as db:
        rows = await (await db.execute("SELECT * FROM voice_sessions WHERE status NOT IN ('closed','rejected') AND (expires<? OR heartbeat<? OR status='closing')", (time.time(), time.time()))).fetchall()
    for row in rows:
        if row['provider_id']:
            await close(row['owner'], row['request_id'])
        elif row['status'] == 'creating':
            await update(row['owner'], row['request_id'], status='uncertain')
    # Bounded metadata retention. Never delete unresolved leases.
    async with get_db() as db:
        await db.execute("DELETE FROM voice_sessions WHERE status IN ('closed','rejected') AND created<?", (time.time() - 7 * 86400,))
        await db.commit()


async def run_reaper():
    while True:
        try:
            await reap_once()
        except Exception:
            logger.exception('Voice lease cleanup failed')
        await asyncio.sleep(10)


async def startup():
    global _reaper
    await init()
    _reaper = asyncio.create_task(run_reaper())


async def shutdown():
    if _reaper:
        _reaper.cancel()
        await asyncio.gather(_reaper, return_exceptions=True)
    if _creates:
        await asyncio.gather(*_creates, return_exceptions=True)
    async with get_db() as db:
        rows = await (await db.execute("SELECT owner,request_id FROM voice_sessions WHERE status NOT IN ('closed','rejected')")).fetchall()
    await asyncio.gather(*(close(r['owner'], r['request_id']) for r in rows), return_exceptions=True)
