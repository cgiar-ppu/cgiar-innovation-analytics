"""Azure OpenAI migration (2026-10-05): GA Realtime voice, deployment probe, dictation, no api.openai.com.

Every outbound request is captured by an httpx.MockTransport; a request to any host other than the
configured Azure resource fails the test.
"""
import time
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException

from synapsis import ai_endpoint
from synapsis.voice import config, health
from synapsis.voice import sessions as s

AZ = 'https://syn-ia.openai.azure.com'
KEY = 'azure-test-key-value'


@pytest.fixture(autouse=True)
def azure_env(monkeypatch):
    for name in ('IA_OPENAI_ENDPOINT', 'IA_VOICE_PROTOCOL', 'IA_VOICE_MODEL', 'IA_VOICE_BACKEND_MODEL', 'IA_VOICE_TRANSCRIBE_MODEL', 'IA_TRANSCRIBE_MODELS'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('OPENAI_API_KEY', KEY)
    health.invalidate()
    yield
    health._transport = None
    health.invalidate()


class Recorder:
    """Patch httpx.AsyncClient so every request goes through a handler; refuse anything outside Azure."""
    def __init__(self, monkeypatch, handler):
        self.requests = []
        real = httpx.AsyncClient

        def factory(*args, **kwargs):
            if not isinstance(kwargs.get('transport'), httpx.ASGITransport):  # the test's own app client passes through
                kwargs['transport'] = httpx.MockTransport(self._handle)
            return real(*args, **kwargs)
        self.handler = handler
        monkeypatch.setattr(httpx, 'AsyncClient', factory)

    def _handle(self, request):
        assert request.url.host == 'syn-ia.openai.azure.com', f'unexpected host {request.url.host}'
        self.requests.append(request)
        return self.handler(request)


def realtime_ok(request):
    path = request.url.path
    if path == '/openai/v1/realtime/client_secrets':
        return httpx.Response(200, json={'value': 'ek_ephemeral', 'expires_at': int(time.time()) + 60, 'session': {}})
    if path == '/openai/v1/realtime/calls':
        return httpx.Response(201, text='v=0\r\nanswer', headers={'Location': '/v1/realtime/calls/rtc_abc123'})
    if path.endswith('/hangup'):
        return httpx.Response(200)
    return httpx.Response(404)


@pytest.fixture
async def voice_db(initialized_db):
    await s.init()
    yield


def test_defaults_are_azure_realtime_interim_models():
    assert ai_endpoint.endpoint() == AZ and ai_endpoint.is_azure()
    assert ai_endpoint.auth_headers() == {'api-key': KEY}
    assert ai_endpoint.v1('realtime/calls') == AZ + '/openai/v1/realtime/calls'
    assert ai_endpoint.provider_label() == 'Microsoft Azure OpenAI'
    assert config.protocol() == 'realtime' and config.model() == 'gpt-realtime-mini'
    assert config.transcription_model() == 'gpt-4o-transcribe'


def test_target_models_are_configuration_only(monkeypatch):
    monkeypatch.setenv('IA_VOICE_PROTOCOL', 'live')
    assert config.model() == 'gpt-live-1' and config.backend_model() == 'gpt-5.6-terra'
    monkeypatch.setenv('IA_VOICE_MODEL', 'gpt-live-2')
    monkeypatch.setenv('IA_VOICE_BACKEND_MODEL', 'gpt-6-luna')
    assert config.session_config()['model'] == 'gpt-live-2'
    assert config.session_config()['delegation']['responses']['model'] == 'gpt-6-luna'
    monkeypatch.setenv('IA_VOICE_PROTOCOL', 'bogus')
    assert config.protocol() == 'realtime'
    monkeypatch.setenv('IA_VOICE_MODEL', '')  # empty CI variable falls back to the protocol default
    assert config.model() == 'gpt-realtime-mini'
    monkeypatch.setenv('IA_OPENAI_ENDPOINT', 'https://api.openai.com/')
    assert not ai_endpoint.is_azure() and ai_endpoint.v1('live/sessions') == 'https://api.openai.com/v1/live/sessions'
    assert ai_endpoint.auth_headers() == {'Authorization': 'Bearer ' + KEY}


def test_realtime_session_keeps_rules_tools_and_brief():
    session = config.realtime_session_config()
    live = config.session_config()
    assert session['type'] == 'realtime' and session['model'] == 'gpt-realtime-mini'
    assert [t['name'] for t in session['tools']] == [t['name'] for t in live['delegation']['responses']['tools']]
    assert all('strict' not in t and t['parameters']['additionalProperties'] is False for t in session['tools'])
    assert config.DELEGATE_SENTENCE not in session['instructions']
    assert 'Never invent counts' in session['instructions'] and 'Read_app before actions' in session['instructions']
    assert session['audio']['input']['transcription'] == {'model': 'gpt-4o-transcribe'}
    assert session['audio']['output']['voice'] == 'marin'


async def test_realtime_create_mints_secret_then_exchanges_sdp_server_side(voice_db, monkeypatch):
    rec = Recorder(monkeypatch, realtime_ok)
    rid = str(uuid4())
    view = await s.create('alice', rid, 'v=0\r\noffer')
    assert view['transport']['sdp'] == 'v=0\r\nanswer'
    assert 'ek_ephemeral' not in str(view)  # the ephemeral secret never reaches the browser
    mint, call = rec.requests
    assert mint.headers['api-key'] == KEY and 'authorization' not in mint.headers
    body = __import__('json').loads(mint.content)
    assert body['session']['model'] == 'gpt-realtime-mini' and body['session']['type'] == 'realtime'
    assert call.headers['authorization'] == 'Bearer ek_ephemeral' and call.headers['content-type'] == 'application/sdp'
    assert 'api-key' not in call.headers and call.content == b'v=0\r\noffer'
    row = await s.get('alice', rid)
    assert row['status'] == 'active' and row['provider_id'] == 'rtc_abc123'
    assert (await s.close('alice', rid))['closed']
    hangup = rec.requests[-1]
    assert hangup.url.path == '/openai/v1/realtime/calls/rtc_abc123/hangup' and hangup.headers['api-key'] == KEY


async def test_realtime_mint_rejection_maps_like_live(voice_db, monkeypatch):
    Recorder(monkeypatch, lambda r: httpx.Response(401, json={'error': {'message': 'key SECRET'}}))
    with pytest.raises(HTTPException) as error:
        await s.create('alice', str(uuid4()), 'v=0\r\noffer')
    assert error.value.status_code == 503 and 'HTTP 401' in error.value.detail and 'SECRET' not in error.value.detail
    Recorder(monkeypatch, lambda r: httpx.Response(400, json={'error': {'code': 'OpperationNotSupported'}}))
    rid = str(uuid4())
    with pytest.raises(HTTPException) as error:
        await s.create('bob', rid, 'v=0\r\noffer')
    assert error.value.status_code == 503 and (await s.get('bob', rid))['status'] == 'rejected'


async def test_realtime_call_without_location_is_incomplete(voice_db, monkeypatch):
    def handler(request):
        if request.url.path.endswith('client_secrets'):
            return httpx.Response(200, json={'value': 'ek_x'})
        return httpx.Response(201, text='v=0\r\nanswer')
    Recorder(monkeypatch, handler)
    rid = str(uuid4())
    with pytest.raises(HTTPException) as error:
        await s.create('carol', rid, 'v=0\r\noffer')
    assert error.value.status_code == 502 and (await s.get('carol', rid))['status'] == 'uncertain'


async def test_live_protocol_on_azure_uses_live_path_and_api_key(voice_db, monkeypatch):
    monkeypatch.setenv('IA_VOICE_PROTOCOL', 'live')
    def handler(request):
        if request.url.path == '/openai/v1/live/sessions':
            return httpx.Response(201, json={'session': {'id': 'live_1'}, 'transport': {'sdp': 'v=0\r\nanswer'}})
        return httpx.Response(200)
    rec = Recorder(monkeypatch, handler)
    rid = str(uuid4())
    await s.create('dave', rid, 'v=0\r\noffer')
    assert rec.requests[0].headers['api-key'] == KEY
    assert __import__('json').loads(rec.requests[0].content)['session']['delegation']['responses']['model'] == 'gpt-5.6-terra'
    await s.close('dave', rid)
    assert rec.requests[-1].url.path == '/openai/v1/live/sessions/live_1/hangup'


async def test_azure_probe_checks_the_deployment_not_the_catalogue(monkeypatch):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200 if request.url.path.endswith('/gpt-realtime-mini') else 404)
    health._transport = httpx.MockTransport(handler)
    assert await health.provider_ok() is True
    assert str(calls[0].url) == AZ + '/openai/deployments/gpt-realtime-mini?api-version=2022-12-01'
    assert calls[0].headers['api-key'] == KEY
    # Live needs both deployments; gpt-live-1 is not deployed here -> unavailable, status surfaced.
    monkeypatch.setenv('IA_VOICE_PROTOCOL', 'live')
    health.invalidate()
    assert await health.provider_ok() is False and health.snapshot()['provider_status'] == 404


async def test_status_route_reports_protocol_and_provider(initialized_db, monkeypatch):
    from fastapi import FastAPI
    from synapsis.auth import middleware
    from synapsis.routes.voice import router
    health._cache.update(ok=True, checked=time.time(), status=200)
    monkeypatch.setenv('IA_VOICE_ENABLED', 'true')
    app = FastAPI(); app.include_router(router)
    app.dependency_overrides[middleware.get_current_user] = lambda: {'user_id': 'alice'}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        body = (await client.get('/api/voice/status')).json()
    assert body['protocol'] == 'realtime' and body['provider'] == 'Microsoft Azure OpenAI' and body['provider_ok'] is True


async def test_dictation_uses_azure_deployment_path(monkeypatch):
    from fastapi import FastAPI
    from synapsis.auth import middleware
    from synapsis.routes import transcribe
    rec = Recorder(monkeypatch, lambda r: httpx.Response(200, json={'text': 'hello world'}))
    app = FastAPI(); app.include_router(transcribe.router)
    app.dependency_overrides[middleware.get_current_user] = lambda: {'user_id': 'alice'}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        r = await client.post('/api/transcribe', files={'file': ('a.webm', b'x' * 500, 'audio/webm;codecs=opus')})
    assert r.status_code == 200 and r.json() == {'text': 'hello world'}
    (req,) = rec.requests
    assert req.url.path == '/openai/deployments/gpt-4o-transcribe/audio/transcriptions'
    assert req.url.params['api-version'] == '2025-03-01-preview' and req.headers['api-key'] == KEY


@pytest.mark.parametrize('module,path,payload', [
    ('tts', '/api/tts', {'text': 'hello'}),
    ('images', '/api/images/generate', {'prompt': 'a cow'}),
])
async def test_tts_and_images_refuse_without_calling_openai(monkeypatch, module, path, payload):
    import importlib
    from fastapi import FastAPI
    from synapsis.auth import middleware
    Recorder(monkeypatch, lambda r: pytest.fail('no outbound call expected'))
    mod = importlib.import_module('synapsis.routes.' + module)
    app = FastAPI(); app.include_router(mod.router)
    app.dependency_overrides[middleware.get_current_user] = lambda: {'user_id': 'alice'}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        r = await client.post(path, json=payload)
    assert r.status_code == 503 and 'not available' in r.json()['detail']


def test_no_hardcoded_openai_host_in_voice_or_dictation_paths():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    for rel in ('synapsis/voice/sessions.py', 'synapsis/voice/health.py', 'synapsis/routes/transcribe.py'):
        assert 'api.openai.com' not in (root / rel).read_text(), rel
