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
    data = lookup('COUNT DISTINCT result_code', 'dashboard_sql', 60)
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
