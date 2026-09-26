"""Meaningful voice boundaries: identity, duplicate starts, cancellation and expiry."""
import asyncio
import time
from uuid import uuid4
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import HTTPException
from synapsis.voice import sessions as s
from synapsis.voice.knowledge import lookup, data_catalog
from synapsis.voice.config import session_config


@pytest.fixture
async def voice_db(initialized_db):
    await s.init()
    yield


def answer():
    return httpx.Response(201, json={'session': {'id': 'live_test'}, 'transport': {'sdp': 'v=0\r\nanswer'}})


async def test_create_replay_owner_and_close(voice_db):
    rid = str(uuid4())
    with patch.object(s, 'provider', AsyncMock(return_value=answer())) as provider:
        first = await s.create('alice', rid, 'v=0\r\noffer')
        assert first == await s.create('alice', rid, 'v=0\r\noffer')
        assert provider.await_count == 1
        # Bob's matching ID cannot end Alice's call.
        assert (await s.close('bob', rid))['closed']
        assert (await s.get('alice', rid))['status'] == 'active'
        with pytest.raises(HTTPException) as error:
            await s.create('alice', str(uuid4()), 'v=0\r\nnew')
        assert error.value.status_code == 409
        assert (await s.close('alice', rid))['closed']
        assert provider.await_count == 2
        assert (await s.close('alice', rid))['closed']
        assert provider.await_count == 2


async def test_cancel_before_and_during_create(voice_db):
    rid = str(uuid4())
    await s.close('alice', rid)
    with pytest.raises(HTTPException):
        await s.create('alice', rid, 'v=0\r\noffer')
    gate = asyncio.Event()
    started = asyncio.Event()
    async def upstream(path, body=None):
        if path == 'sessions':
            started.set()
            await gate.wait()
            return answer()
        return httpx.Response(200)
    with patch.object(s, 'provider', upstream):
        rid = str(uuid4())
        task = asyncio.create_task(s.create('alice', rid, 'v=0\r\noffer'))
        await started.wait()
        assert not (await s.close('alice', rid))['closed']
        gate.set()
        with pytest.raises(HTTPException):
            await task
        assert (await s.get('alice', rid))['status'] == 'closed'


async def test_expiry_and_failed_hangup_keep_lease(voice_db):
    rid = str(uuid4())
    with patch.object(s, 'provider', AsyncMock(return_value=answer())):
        await s.create('alice', rid, 'v=0\r\noffer')
    await s.update('alice', rid, expires=time.time() - 1)
    with patch.object(s, 'provider', AsyncMock(return_value=httpx.Response(500))):
        await s.reap_once()
        assert (await s.get('alice', rid))['status'] == 'closing'
        with pytest.raises(HTTPException):
            await s.heartbeat('alice', rid)
    with patch.object(s, 'provider', AsyncMock(return_value=httpx.Response(200))):
        await s.reap_once()
        assert (await s.get('alice', rid))['status'] == 'closed'


async def test_unknown_creation_never_retried(voice_db):
    with patch.object(s, 'provider', AsyncMock(side_effect=httpx.ReadTimeout('lost reply'))) as provider:
        with pytest.raises(HTTPException):
            await s.create('alice', str(uuid4()), 'v=0\r\noffer')
        with pytest.raises(HTTPException) as error:
            await s.create('alice', str(uuid4()), 'v=0\r\nsecond')
        assert error.value.status_code == 409
        assert provider.await_count == 1


async def test_uncertain_leases_do_not_consume_shared_capacity_and_are_bounded(voice_db, caplog):
    # Six different owners hit a provider timeout: six 'uncertain' leases without a provider ID.
    rids = {f'user{i}': str(uuid4()) for i in range(6)}
    with patch.object(s, 'provider', AsyncMock(side_effect=httpx.ReadTimeout('lost reply'))):
        for owner, rid in rids.items():
            with pytest.raises(HTTPException):
                await s.create(owner, rid, 'v=0\r\noffer')
    for owner, rid in rids.items():
        assert (await s.get(owner, rid))['status'] == 'uncertain'
    # Before: the seventh person got 429 forever. Now the pool is untouched by uncertain rows.
    rid = str(uuid4())
    with patch.object(s, 'provider', AsyncMock(return_value=answer())):
        assert (await s.create('user6', rid, 'v=0\r\noffer'))['request_id'] == rid
    # ...but each affected owner is still blocked by their own uncertain lease, briefly (L6-08),
    # and is told roughly how long.
    with pytest.raises(HTTPException) as error:
        await s.create('user0', str(uuid4()), 'v=0\r\nagain')
    assert error.value.status_code == 409
    assert 'Try again in about 2 minutes' in error.value.detail
    # The reaper leaves young uncertain rows alone, then releases them after the short window
    # (90 s, was the 11-minute maximum call length: no answer was delivered, so no media exists).
    await s.reap_once()
    assert (await s.get('user0', rids['user0']))['status'] == 'uncertain'
    for owner, rid in rids.items():
        await s.update(owner, rid, created=time.time() - s.UNCERTAIN_NO_ID_RELEASE_SECONDS - 1)
    with caplog.at_level('WARNING', logger='synapsis_agent'):
        await s.reap_once()
    row = await s.get('user0', rids['user0'])
    assert row['status'] == 'closed_unconfirmed' and row['closed']
    assert sum('voice_lease_unconfirmed' in r.message and 'reason=no_provider_id_no_answer_delivered' in r.message for r in caplog.records) == 6
    with patch.object(s, 'provider', AsyncMock(return_value=answer())):
        await s.create('user0', str(uuid4()), 'v=0\r\nagain')  # owner released
    assert (await s.usage_today())['sessions'] == 0  # unconfirmed leases never count as usage


async def test_reaper_hangs_up_known_uncertain_sessions_with_backoff_and_gives_up(voice_db, caplog):
    from synapsis.database import get_db
    rid = str(uuid4())
    now = time.time()
    async with get_db() as db:
        await db.execute("INSERT INTO voice_sessions(owner,request_id,sdp_hash,status,provider_id,created,expires,heartbeat) VALUES (?,?,?,?,?,?,?,?)",
                         ('dave', rid, 'h', 'uncertain', 'live_ghost', now, now + 600, now + 60))
        await db.commit()
    failing = AsyncMock(return_value=httpx.Response(500))
    with patch.object(s, 'provider', failing):
        await s.reap_once()
        await s.reap_once()  # inside the 60 s backoff: no second call
    assert failing.await_count == 1
    row = await s.get('dave', rid)
    assert row['status'] == 'uncertain' and row['attempts'] == 1 and row['attempted'] >= now
    # Still not counted against the shared pool, still blocking dave.
    with pytest.raises(HTTPException) as error:
        await s.create('dave', str(uuid4()), 'v=0\r\noffer')
    assert error.value.status_code == 409
    await s.update('dave', rid, attempted=now - 61)
    with patch.object(s, 'provider', AsyncMock(return_value=httpx.Response(200))):
        await s.reap_once()
    row = await s.get('dave', rid)
    assert row['status'] == 'closed' and row['provider_status'] == 200 and row['attempts'] == 2
    # Attempts exhausted -> closed_unconfirmed with the IDs an operator needs.
    rid2 = str(uuid4())
    async with get_db() as db:
        await db.execute("INSERT INTO voice_sessions(owner,request_id,sdp_hash,status,provider_id,created,expires,heartbeat,attempts,attempted) VALUES (?,?,?,?,?,?,?,?,?,?)",
                         ('erin', rid2, 'h', 'closing', 'live_stuck', now, now + 600, now + 60, s.MAX_HANGUP_ATTEMPTS, now))
        await db.commit()
    with patch.object(s, 'provider', failing), caplog.at_level('WARNING', logger='synapsis_agent'):
        await s.reap_once()
    assert (await s.get('erin', rid2))['status'] == 'closed_unconfirmed'
    assert any(f'voice_lease_unconfirmed owner=erin request_id={rid2} provider_id=live_stuck attempts=8' in r.message for r in caplog.records)
    assert failing.await_count == 1
    assert s._backoff(0) == 0 and s._backoff(1) == 60 and s._backoff(4) == 480 and s._backoff(9) == 600


async def test_init_upgrades_legacy_table_in_place(initialized_db):
    from synapsis.database import get_db
    async with get_db() as db:
        await db.execute('''CREATE TABLE voice_sessions (owner TEXT NOT NULL, request_id TEXT NOT NULL, sdp_hash TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL, provider_id TEXT, answer TEXT, created REAL NOT NULL, expires REAL NOT NULL, heartbeat REAL NOT NULL, PRIMARY KEY(owner, request_id))''')
        await db.execute("INSERT INTO voice_sessions VALUES ('old','r1','h','closed',NULL,NULL,1,2,3)")
        await db.commit()
    await s.init()
    await s.init()  # idempotent
    async with get_db() as db:
        columns = {row[1] for row in await (await db.execute('PRAGMA table_info(voice_sessions)')).fetchall()}
    assert set(s.EXTRA_COLUMNS) <= columns
    assert (await s.get('old', 'r1'))['status'] == 'closed'
    # Old rows and the create path both work with the widened schema.
    with patch.object(s, 'provider', AsyncMock(return_value=answer())):
        assert (await s.create('old', str(uuid4()), 'v=0\r\noffer'))['max_seconds'] == 600


async def test_close_records_usage_and_emits_structured_line(voice_db, caplog):
    rid = str(uuid4())
    with patch.object(s, 'provider', AsyncMock(return_value=answer())), caplog.at_level('INFO', logger='synapsis_agent'):
        await s.create('alice', rid, 'v=0\r\noffer')
        await s.update('alice', rid, created=time.time() - 42)
        assert (await s.close('alice', rid, provider_seconds=40.4))['closed']
    row = await s.get('alice', rid)
    assert row['status'] == 'closed' and row['closed'] > row['created'] and row['answer'] is None
    assert 41 <= row['usage_seconds'] <= 45 and row['provider_seconds'] == 40.4 and row['provider_status'] == 201
    line = next(r.message for r in caplog.records if r.message.startswith('voice_session_closed'))
    assert f'owner=alice request_id={rid} seconds=4' in line and 'provider_seconds=40' in line and 'provider_status=201' in line
    assert any(r.message.startswith(f'voice_session_started owner=alice request_id={rid} provider_id=live_test') for r in caplog.records)
    assert await s.usage_today() == {'sessions': 1, 'seconds': 40}
    # A late client report after the reaper already closed the lease is kept; tombstones never count.
    rid2 = str(uuid4())
    with patch.object(s, 'provider', AsyncMock(return_value=answer())):
        await s.create('bob', rid2, 'v=0\r\noffer')
        await s.close('bob', rid2)
        await s.close('bob', rid2, provider_seconds=12)
    assert (await s.get('bob', rid2))['provider_seconds'] == 12
    await s.close('carol', str(uuid4()), provider_seconds=999)
    assert (await s.usage_today())['sessions'] == 2


async def test_status_daily_usage_is_admin_only(voice_db, monkeypatch):
    from fastapi import FastAPI
    from synapsis.routes.voice import router
    from synapsis.auth import middleware
    from synapsis.voice import health
    health._cache.update(ok=True, checked=time.time(), status=200)
    app = FastAPI()
    app.include_router(router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        app.dependency_overrides[middleware.get_current_user] = lambda: {'user_id': 'alice', 'role': 'user'}
        assert 'usage_today' not in (await client.get('/api/voice/status')).json()
        app.dependency_overrides[middleware.get_current_user] = lambda: {'user_id': 'root', 'role': 'admin'}
        assert (await client.get('/api/voice/status')).json()['usage_today'] == {'sessions': 0, 'seconds': 0}
        rid = str(uuid4())
        assert (await client.post(f'/api/voice/sessions/{rid}/close', json={'usage_seconds': -1})).status_code == 422
        assert (await client.post(f'/api/voice/sessions/{rid}/close', json={'extra': 1})).status_code == 422
        assert (await client.post(f'/api/voice/sessions/{rid}/close', json={})).json() == {'closed': True}
        assert (await client.post(f'/api/voice/sessions/{rid}/close')).json() == {'closed': True}


async def test_limit_messages_are_environment_neutral(voice_db):
    # Per-user burst limit: four starts within a minute; the fifth is refused.
    with patch.object(s, 'provider', AsyncMock(return_value=answer())):
        for _ in range(4):
            rid = str(uuid4())
            await s.create('carol', rid, 'v=0\r\noffer')
            await s.close('carol', rid)
        with pytest.raises(HTTPException) as error:
            await s.create('carol', str(uuid4()), 'v=0\r\noffer')
    assert error.value.status_code == 429
    assert 'development' not in error.value.detail.lower()
    import inspect
    assert 'development' not in inspect.getsource(s.create).lower()


async def test_provider_rejection_names_status_but_never_body(voice_db, caplog):
    from synapsis.voice import health
    health._cache.update(ok=True, checked=time.time(), status=200)
    body = {'error': {'message': 'Incorrect API key provided: sk-live-SECRET'}}
    with patch.object(s, 'provider', AsyncMock(return_value=httpx.Response(401, json=body))):
        with caplog.at_level('WARNING', logger='synapsis_agent'):
            with pytest.raises(HTTPException) as error:
                await s.create('alice', str(uuid4()), 'v=0\r\noffer')
    assert error.value.status_code == 503
    assert 'HTTP 401' in error.value.detail and 'API key' in error.value.detail
    assert 'SECRET' not in error.value.detail and 'SECRET' not in caplog.text
    assert any('voice_create_rejected' in r.message and 'provider_status=401' in r.message for r in caplog.records)
    assert health.snapshot()['provider_ok'] is None  # 401 invalidates the cached probe
    rid = str(uuid4())
    with patch.object(s, 'provider', AsyncMock(return_value=httpx.Response(503))):
        with pytest.raises(HTTPException) as error:
            await s.create('bob', rid, 'v=0\r\noffer')
    assert error.value.status_code == 502 and 'HTTP 503' in error.value.detail
    assert (await s.get('bob', rid))['status'] == 'uncertain'


async def test_http_auth_origin_and_config(voice_db, monkeypatch):
    from fastapi import FastAPI
    from synapsis.routes.voice import router
    from synapsis.auth import middleware
    monkeypatch.setattr(middleware, 'AUTH_DISABLED', False)
    app = FastAPI()
    app.include_router(router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        for method, url in [('GET','/api/voice/status'), ('POST','/api/voice/sessions'), ('POST','/api/voice/knowledge'), ('GET','/api/voice/data-catalog')]:
            assert (await client.request(method, url, json={})).status_code == 401
        app.dependency_overrides[middleware.get_current_user] = lambda: {'user_id': 'alice'}
        assert (await client.get('/api/voice/status', headers={'Origin':'https://evil.example'})).status_code == 403
        assert (await client.post('/api/voice/knowledge', json={'query':'secret','source':'../../.env'})).status_code == 422
        assert (await client.post('/api/voice/sessions', json={'request_id':str(uuid4()),'sdp':'v=0\r\noffer','model':'other'})).status_code == 422
        monkeypatch.setenv('IA_VOICE_ENABLED', 'false')
        assert (await client.post('/api/voice/sessions', json={'request_id':str(uuid4()),'sdp':'v=0\r\noffer'})).status_code == 503


def test_knowledge_is_shipped_grounded_and_bounded():
    data = lookup('COUNT DISTINCT result_code', 'dashboard_sql')
    assert data['excerpts'][0]['file'] == 'synapsis/routes/prms_dashboard.py'
    assert 'COUNT(DISTINCT result_code)' in data['excerpts'][0]['text']
    assert len(data['excerpts']) <= 4
    for source in lookup('')['sources']:
        assert lookup('', source, 1)['excerpts'], source
    with pytest.raises(ValueError):
        lookup('password', '/etc/passwd')
    config = session_config()
    assert config['store'] is False
    assert all(t['parameters']['additionalProperties'] is False for t in config['delegation']['responses']['tools'])
    assert 'execute_code' not in str(config['delegation']['responses']['tools'])


def test_container_declares_voice_http_dependency():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    assert any(line.startswith('httpx>=') for line in (root / 'requirements.txt').read_text().splitlines())
    assert 'from synapsis.server import app' in (root / 'Dockerfile.prod').read_text()


# ---------------------------------------------------------------------------
# Review L6-08: one provider failure no longer locks a user out for 11–45 min
# ---------------------------------------------------------------------------

async def test_failed_start_releases_the_owner_after_90_seconds_without_waiting_for_the_reaper(voice_db):
    rid = str(uuid4())
    with patch.object(s, 'provider', AsyncMock(return_value=httpx.Response(503))):
        with pytest.raises(HTTPException) as error:
            await s.create('frank', rid, 'v=0\r\noffer')
    assert error.value.status_code == 502
    assert (await s.get('frank', rid))['status'] == 'uncertain'
    with pytest.raises(HTTPException) as error:
        await s.create('frank', str(uuid4()), 'v=0\r\nagain')
    assert error.value.status_code == 409
    # 91 s later the lease no longer blocks, even before the reaper has run.
    await s.update('frank', rid, created=time.time() - s.UNCERTAIN_NO_ID_RELEASE_SECONDS - 1)
    new_rid = str(uuid4())
    with patch.object(s, 'provider', AsyncMock(return_value=answer())):
        assert (await s.create('frank', new_rid, 'v=0\r\nagain'))['request_id'] == new_rid


async def test_known_provider_session_blocks_owner_for_at_most_one_call_length(voice_db):
    from synapsis.database import get_db
    now = time.time()
    rid = str(uuid4())
    async with get_db() as db:
        await db.execute("INSERT INTO voice_sessions(owner,request_id,sdp_hash,status,provider_id,created,expires,heartbeat) VALUES (?,?,?,?,?,?,?,?)",
                         ('gina', rid, 'h', 'closing', 'live_slow_hangup', now - 300, now + 300, now - 1))
        await db.commit()
    with pytest.raises(HTTPException) as error:
        await s.create('gina', str(uuid4()), 'v=0\r\noffer')
    assert error.value.status_code == 409 and 'about 6 minutes' in error.value.detail
    # Past the 10-minute limit + heartbeat the call cannot still be connected: the owner is free,
    # while the reaper keeps retrying the hang-up for the old lease in the background.
    await s.update('gina', rid, created=now - s.MAX_SECONDS - s.HEARTBEAT_SECONDS - 1)
    with patch.object(s, 'provider', AsyncMock(return_value=answer())):
        await s.create('gina', str(uuid4()), 'v=0\r\nagain')
    assert (await s.get('gina', rid))['status'] == 'closing'


async def test_active_lease_still_blocks_its_owner_without_a_time_hint(voice_db):
    with patch.object(s, 'provider', AsyncMock(return_value=answer())):
        await s.create('hana', str(uuid4()), 'v=0\r\noffer')
        with pytest.raises(HTTPException) as error:
            await s.create('hana', str(uuid4()), 'v=0\r\nsecond')
    assert error.value.status_code == 409
    assert 'End it before starting another.' in error.value.detail


async def test_released_failures_still_count_towards_the_daily_start_cap(voice_db):
    from synapsis.database import get_db
    now = time.time()
    async with get_db() as db:
        for i in range(20):  # 20 earlier failed starts today, all already released
            await db.execute("INSERT INTO voice_sessions(owner,request_id,sdp_hash,status,created,expires,heartbeat,closed) VALUES (?,?,?,?,?,?,?,?)",
                             ('ivan', str(uuid4()), 'h', 'closed_unconfirmed', now - 3600 - i, now, now, now))
        await db.commit()
    with pytest.raises(HTTPException) as error:
        await s.create('ivan', str(uuid4()), 'v=0\r\noffer')
    assert error.value.status_code == 429


def test_owner_block_seconds_rules():
    now = 10_000.0
    assert s.owner_block_seconds({'status': 'active', 'provider_id': 'x', 'created': now}, now) == float('inf')
    assert s.owner_block_seconds({'status': 'creating', 'provider_id': None, 'created': now}, now) == float('inf')
    assert s.owner_block_seconds({'status': 'uncertain', 'provider_id': None, 'created': now - 30}, now) == 60
    assert s.owner_block_seconds({'status': 'uncertain', 'provider_id': None, 'created': now - 91}, now) == 0
    assert s.owner_block_seconds({'status': 'closing', 'provider_id': 'x', 'created': now - 60}, now) == 600


def test_navigate_does_not_offer_the_admin_only_agents_page():
    """Wave 3b: the Agents page is admin-only, so the guide never proposes it (the
    browser adapter still refuses it for non-admins). submit_feedback (Lane H) stays."""
    tools = session_config()['delegation']['responses']['tools']
    navigate = next(t for t in tools if t['name'] == 'navigate')
    assert navigate['parameters']['properties']['page']['enum'] == ['dashboard', 'chat', 'settings']
    assert 'submit_feedback' in [t['name'] for t in tools]
    assert 'navigate Dashboard, Chat, Agents' not in session_config()['instructions']
