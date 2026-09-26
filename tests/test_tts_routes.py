"""Read-aloud (TTS) and dictation routes (review L6-05/06/07).

* every TTS route requires a signed-in user (the frontend now sends the token);
* the model is pinned server-side, text/instructions are capped, voices and
  formats are allow-listed, and each user has a per-minute budget;
* the server-wide default settings are administrator-only;
* dictation caps the upload and never echoes the provider's error text.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from synapsis.routes import tts


@pytest.fixture
async def enforced_client(initialized_db):
    with (
        patch("synapsis.config.AUTH_DISABLED", False),
        patch("synapsis.auth.middleware.AUTH_DISABLED", False),
    ):
        from synapsis.server import app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path,body", [
    ("post", "/api/tts", {"text": "Hello."}),
    ("get", "/api/tts/voices", None),
    ("post", "/api/tts/settings", {"voice": "sage"}),
])
async def test_tts_routes_require_a_signed_in_user(enforced_client, method, path, body):
    kwargs = {"json": body} if body is not None else {}
    resp = await getattr(enforced_client, method)(path, **kwargs)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_transcribe_requires_a_signed_in_user(enforced_client):
    resp = await enforced_client.post("/api/transcribe", files={"file": ("a.webm", b"x" * 200, "audio/webm")})
    assert resp.status_code == 401


def test_model_is_pinned_and_inputs_are_allow_listed():
    req = tts.TTSRequest(text="Hi.", model="gpt-some-expensive-model", voice="not-a-voice", response_format="exe")
    params = tts._effective_settings(req)
    assert params["model"] == tts._tts_settings["model"]
    assert params["voice"] == tts._tts_settings["voice"]
    assert params["response_format"] == "opus"
    ok = tts._effective_settings(tts.TTSRequest(text="Hi.", voice="sage", response_format="mp3", speed=1.2))
    assert ok["voice"] == "sage" and ok["response_format"] == "mp3" and ok["speed"] == 1.2


def test_text_and_instructions_are_capped():
    with pytest.raises(ValidationError):
        tts.TTSRequest(text="x" * (tts.MAX_TEXT_CHARS + 1))
    with pytest.raises(ValidationError):
        tts.TTSRequest(text="")
    with pytest.raises(ValidationError):
        tts.TTSRequest(text="ok", instructions="y" * (tts.MAX_INSTRUCTIONS_CHARS + 1))


def test_per_user_rate_limit(monkeypatch):
    monkeypatch.setattr(tts, "REQUESTS_PER_MINUTE", 3)
    tts._recent.clear()
    for i in range(3):
        tts._check_rate("alice", now=100.0 + i)
    with pytest.raises(HTTPException) as err:
        tts._check_rate("alice", now=104.0)
    assert err.value.status_code == 429
    tts._check_rate("bob", now=104.0)  # other users are unaffected
    tts._check_rate("alice", now=165.0)  # the window slides
    tts._recent.clear()


def test_settings_are_admin_only():
    with pytest.raises(HTTPException) as err:
        tts._require_admin({"user_id": "u1", "role": "researcher"})
    assert err.value.status_code == 403
    assert tts._require_admin({"user_id": "a1", "role": "admin"})["role"] == "admin"


@pytest.mark.asyncio
async def test_admin_cannot_set_an_unknown_model(monkeypatch):
    before = dict(tts._tts_settings)
    try:
        with pytest.raises(HTTPException) as err:
            await tts.update_settings(tts.TTSSettingsUpdate(model="gpt-4o-audio-preview-super"))
        assert err.value.status_code == 400
        await tts.update_settings(tts.TTSSettingsUpdate(model="tts-1"))
        assert tts._tts_settings["model"] == "tts-1"
    finally:
        tts._tts_settings.update(before)


@pytest.mark.asyncio
async def test_missing_key_is_a_clear_503(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(HTTPException) as err:
        await tts.synthesize_speech(tts.TTSRequest(text="Hi."), user={"user_id": "u", "role": "researcher"})
    assert err.value.status_code == 503 and "OPENAI" not in err.value.detail


@pytest.mark.asyncio
async def test_transcribe_caps_upload_size(monkeypatch, initialized_db):
    from synapsis.routes import transcribe

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(transcribe, "MAX_AUDIO_BYTES", 1000)
    with patch("synapsis.config.AUTH_DISABLED", True), patch("synapsis.auth.middleware.AUTH_DISABLED", True):
        from synapsis.server import app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/transcribe", files={"file": ("a.webm", b"x" * 2000, "audio/webm")})
    assert resp.status_code == 413
