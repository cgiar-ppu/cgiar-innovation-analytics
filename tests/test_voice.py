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
