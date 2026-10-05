"""
Text-to-speech routes using OpenAI's gpt-4o-mini-tts model (read-aloud).

Provides streaming audio synthesis, voice listing, and runtime settings
management.  Requires OPENAI_API_KEY environment variable (per environment:
deploy.yml puts SSM ``/cgiar-ia-<stage>/openai-api-key`` into the container).

Every route requires a signed-in user (``Authorization: Bearer``; the
frontend's read-aloud used to send no token and silently got 401 — review
L6-05). Cost guards (review L6-06/L6-07): the model is pinned server-side
(``SYNAPSIS_TTS_MODEL``), the text and instructions are capped, voices and
formats are allow-listed, each user has a per-minute request budget, and the
process-wide default settings can only be changed by an administrator (a
user's own voice/speed preferences travel with each request instead).
"""

import os
import time
from collections import defaultdict, deque

from fastapi import APIRouter, HTTPException, Depends
from synapsis.auth.middleware import get_current_user, resolve_role, resolve_user_id
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Optional

from synapsis.config import (
    logger, TTS_MODEL, TTS_VOICE, TTS_INSTRUCTIONS, TTS_SPEED,
)

router = APIRouter(dependencies=[Depends(get_current_user)])
# ---------------------------------------------------------------------------
# Runtime-mutable settings (initialised from config, updated via API)
# ---------------------------------------------------------------------------

_tts_settings: dict = {
    "voice": TTS_VOICE,
    "model": TTS_MODEL,
    "instructions": TTS_INSTRUCTIONS,
    "speed": TTS_SPEED,
}

# All 13 OpenAI voices with descriptions
VOICES = [
    {"id": "alloy", "name": "Alloy", "description": "Neutral and balanced"},
    {"id": "ash", "name": "Ash", "description": "Soft and thoughtful"},
    {"id": "ballad", "name": "Ballad", "description": "Warm and melodic"},
    {"id": "coral", "name": "Coral", "description": "Clear and friendly"},
    {"id": "echo", "name": "Echo", "description": "Smooth and resonant"},
    {"id": "fable", "name": "Fable", "description": "Expressive and storytelling"},
    {"id": "nova", "name": "Nova", "description": "Bright and energetic"},
    {"id": "onyx", "name": "Onyx", "description": "Deep and authoritative"},
    {"id": "sage", "name": "Sage", "description": "Calm and wise"},
    {"id": "shimmer", "name": "Shimmer", "description": "Light and airy"},
    {"id": "verse", "name": "Verse", "description": "Rich and poetic"},
    {"id": "marin", "name": "Marin", "description": "Natural and relaxed"},
    {"id": "cedar", "name": "Cedar", "description": "Grounded and steady"},
]


# ---------------------------------------------------------------------------
# Request/response models
# ---------------------------------------------------------------------------

#: OpenAI's own input limit for /v1/audio/speech; read-aloud sends sentences.
MAX_TEXT_CHARS = 4096
MAX_INSTRUCTIONS_CHARS = 1000
#: Per-user request budget (read-aloud fetches sentence by sentence, two at a time).
REQUESTS_PER_MINUTE = int(os.getenv("IA_TTS_REQUESTS_PER_MINUTE", "120"))
ALLOWED_FORMATS = ("opus", "mp3", "aac", "flac", "wav", "pcm")
#: Models an administrator may set as the server default.
ALLOWED_MODELS = ("gpt-4o-mini-tts", "tts-1", "tts-1-hd")

_recent: dict[str, deque] = defaultdict(deque)


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=MAX_TEXT_CHARS)
    voice: Optional[str] = None
    #: Ignored: the model is pinned server-side (kept for old clients).
    model: Optional[str] = None
    instructions: Optional[str] = Field(None, max_length=MAX_INSTRUCTIONS_CHARS)
    speed: Optional[float] = Field(None, ge=0.25, le=4.0)
    response_format: Optional[str] = "opus"


class TTSSettingsUpdate(BaseModel):
    voice: Optional[str] = None
    model: Optional[str] = None
    instructions: Optional[str] = Field(None, max_length=MAX_INSTRUCTIONS_CHARS)
    speed: Optional[float] = Field(None, ge=0.25, le=4.0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_api_key() -> str:
    # No speech/image deployment exists on the Azure resource (2026-10-05 migration) and the old OpenAI
    # organisation is closed: refuse before any outbound call instead of sending the Azure key to OpenAI.
    from synapsis import ai_endpoint
    if ai_endpoint.is_azure():
        raise HTTPException(status_code=503, detail="Read-aloud (text-to-speech) is not available in this environment.")
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise HTTPException(status_code=503, detail="Read-aloud is not configured on this server.")
    return key


_VOICE_IDS = frozenset(v["id"] for v in VOICES)


def _effective_settings(req: TTSRequest) -> dict:
    """Merge the caller's preferences with the server settings (model pinned)."""
    voice = req.voice if req.voice in _VOICE_IDS else _tts_settings["voice"]
    fmt = req.response_format if req.response_format in ALLOWED_FORMATS else "opus"
    return {
        "model": _tts_settings["model"],
        "voice": voice,
        "input": req.text,
        "instructions": req.instructions if req.instructions is not None else _tts_settings["instructions"],
        "speed": req.speed if req.speed is not None else _tts_settings["speed"],
        "response_format": fmt,
    }


def _check_rate(user_id: str, now: float | None = None) -> None:
    """Per-user sliding one-minute window; 429 when the budget is used up."""
    now = time.monotonic() if now is None else now
    q = _recent[user_id]
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= REQUESTS_PER_MINUTE:
        raise HTTPException(status_code=429, detail="Too many read-aloud requests; try again in a minute.")
    q.append(now)


def _require_admin(user: dict = Depends(get_current_user)) -> dict:
    if resolve_role(user) != "admin":
        raise HTTPException(status_code=403, detail="Administrator access required")
    return user


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/api/tts")
async def synthesize_speech(req: TTSRequest, user: dict = Depends(get_current_user)):
    """Stream synthesised audio from OpenAI's TTS API (signed-in users only)."""
    api_key = _get_api_key()
    _check_rate(resolve_user_id(user))

    try:
        import httpx
    except ImportError:
        raise HTTPException(status_code=500, detail="httpx is required but not installed")

    params = _effective_settings(req)
    content_type = {
        "opus": "audio/opus",
        "mp3": "audio/mpeg",
        "aac": "audio/aac",
        "flac": "audio/flac",
        "wav": "audio/wav",
        "pcm": "audio/pcm",
    }.get(params["response_format"], "audio/opus")

    t0 = time.monotonic()
    logger.info(
        "TTS request: model=%s voice=%s format=%s text_len=%d",
        params["model"], params["voice"], params["response_format"], len(req.text),
    )

    async def _stream():
        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream(
                "POST",
                "https://api.openai.com/v1/audio/speech",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=params,
            ) as resp:
                if resp.status_code != 200:
                    # Status only: the provider body can echo a masked key fragment.
                    logger.error("OpenAI TTS failed: provider_status=%s", resp.status_code)
                    raise HTTPException(status_code=502, detail=f"OpenAI TTS failed: {resp.status_code}")
                async for chunk in resp.aiter_bytes(4096):
                    yield chunk
        elapsed = time.monotonic() - t0
        logger.info("TTS complete: %.1fs", elapsed)

    return StreamingResponse(_stream(), media_type=content_type)


@router.get("/api/tts/voices")
async def list_voices():
    """Return available voices and current TTS settings."""
    return {
        "voices": VOICES,
        "current": {
            "voice": _tts_settings["voice"],
            "model": _tts_settings["model"],
            "instructions": _tts_settings["instructions"],
            "speed": _tts_settings["speed"],
        },
    }


@router.post("/api/tts/settings", dependencies=[Depends(_require_admin)])
async def update_settings(req: TTSSettingsUpdate):
    """Update the server-wide DEFAULT TTS settings (administrators only).

    These defaults apply to every user who has not chosen their own voice or
    speed; users' own choices are kept in their browser and sent with each
    request (review L6-06: any user used to change everyone's voice here).
    """
    if req.voice is not None:
        if req.voice not in _VOICE_IDS:
            raise HTTPException(status_code=400, detail=f"Unknown voice: {req.voice}")
        _tts_settings["voice"] = req.voice
    if req.model is not None:
        if req.model not in ALLOWED_MODELS:
            raise HTTPException(status_code=400, detail=f"Unsupported model: {req.model}")
        _tts_settings["model"] = req.model
    if req.instructions is not None:
        _tts_settings["instructions"] = req.instructions
    if req.speed is not None:
        _tts_settings["speed"] = req.speed

    logger.info("TTS settings updated: %s", _tts_settings)
    return {
        "settings": {
            "voice": _tts_settings["voice"],
            "model": _tts_settings["model"],
            "instructions": _tts_settings["instructions"],
            "speed": _tts_settings["speed"],
        }
    }
