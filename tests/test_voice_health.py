"""Provider probe: cached, failure-safe, never leaks the key, surfaces in /status."""
import asyncio
import logging

import httpx
import pytest
from synapsis.voice import health


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'sk-test-secret-value')
    monkeypatch.setenv('IA_VOICE_MODEL', 'gpt-live-1')
    health.invalidate()
    yield
    health._transport = None
    health.invalidate()


def transport(status=200, calls=None, exc=None):
    def handler(request):
        (calls if calls is not None else []).append(request)
        if exc:
            raise exc
        return httpx.Response(status, json={'id': 'gpt-live-1'})
    return httpx.MockTransport(handler)


async def test_probe_hits_model_endpoint_once_and_caches_success():
    calls = []
    health._transport = transport(200, calls)
    assert await health.provider_ok() is True
    assert await health.provider_ok() is True
    assert len(calls) == 1
    assert calls[0].url == 'https://api.openai.com/v1/models/gpt-live-1'
    assert calls[0].headers['authorization'] == 'Bearer sk-test-secret-value'
    assert health.snapshot()['provider_status'] == 200


async def test_failure_is_cached_and_logged_without_the_key(caplog):
    calls = []
    health._transport = transport(401, calls)
    with caplog.at_level(logging.WARNING, logger='synapsis_agent'):
        assert await health.provider_ok() is False
        assert await health.provider_ok() is False
    assert len(calls) == 1
    assert any('voice_provider_probe_failed' in r.message and 'provider_status=401' in r.message for r in caplog.records)
    assert 'sk-test' not in caplog.text


async def test_network_error_never_raises_and_is_cached():
    calls = []
    health._transport = transport(exc=httpx.ConnectTimeout('slow'), calls=calls)
    assert await health.provider_ok() is False
    assert await health.provider_ok() is False
    assert len(calls) == 1


async def test_cache_expires_and_invalidate_forces_reprobe(monkeypatch):
    calls = []
    health._transport = transport(200, calls)
    assert await health.provider_ok() is True
    health.invalidate()
    assert await health.provider_ok() is True
    assert len(calls) == 2
    monkeypatch.setattr(health, 'CACHE_SECONDS', 0)
    assert await health.provider_ok() is True
    assert len(calls) == 3


async def test_concurrent_status_calls_share_one_probe():
    calls = []
    health._transport = transport(200, calls)
    assert await asyncio.gather(*(health.provider_ok() for _ in range(5))) == [True] * 5
    assert len(calls) == 1


async def test_unconfigured_returns_none_without_probing(monkeypatch):
    calls = []
    health._transport = transport(200, calls)
    monkeypatch.delenv('OPENAI_API_KEY')
    assert await health.provider_ok() is None
    assert calls == []


async def test_status_route_reports_provider_ok(initialized_db, monkeypatch):
    from fastapi import FastAPI
    from synapsis.routes.voice import router
    from synapsis.auth import middleware
    monkeypatch.setenv('IA_VOICE_ENABLED', 'true')
    health._transport = transport(401)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[middleware.get_current_user] = lambda: {'user_id': 'alice'}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        body = (await client.get('/api/voice/status')).json()
    assert body['enabled'] is True and body['configured'] is True and body['provider_ok'] is False
    assert body['max_seconds'] == 600
