"""
Text-to-speech routes using OpenAI's gpt-4o-mini-tts model.

Provides streaming audio synthesis, voice listing, and runtime settings
management.  Requires OPENAI_API_KEY environment variable.
"""

import os
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Optional

from synapsis.config import (
    logger, TTS_MODEL, TTS_VOICE, TTS_INSTRUCTIONS, TTS_SPEED,
)

router = APIRouter()

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

class TTSRequest(BaseModel):
    text: str
    voice: Optional[str] = None
    model: Optional[str] = None
    instructions: Optional[str] = None
    speed: Optional[float] = Field(None, ge=0.25, le=4.0)
    response_format: Optional[str] = "opus"


class TTSSettingsUpdate(BaseModel):
    voice: Optional[str] = None
    model: Optional[str] = None
    instructions: Optional[str] = None
    speed: Optional[float] = Field(None, ge=0.25, le=4.0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_api_key() -> str:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise HTTPException(
            status_code=500,
            detail="OPENAI_API_KEY environment variable is not set. "
                   "Add it to your shell profile or export it before starting the server.",
        )
    return key


def _effective_settings(req: TTSRequest) -> dict:
    """Merge request overrides with current runtime settings."""
    return {
        "model": req.model or _tts_settings["model"],
        "voice": req.voice or _tts_settings["voice"],
        "input": req.text,
        "instructions": req.instructions if req.instructions is not None else _tts_settings["instructions"],
        "speed": req.speed if req.speed is not None else _tts_settings["speed"],
        "response_format": req.response_format or "opus",
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/api/tts")
async def synthesize_speech(req: TTSRequest):
    """Stream synthesised audio from OpenAI's TTS API."""
    api_key = _get_api_key()

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
                    body = await resp.aread()
                    logger.error("OpenAI TTS failed: %s %s", resp.status_code, body[:500])
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


@router.post("/api/tts/settings")
async def update_settings(req: TTSSettingsUpdate):
    """Update runtime TTS settings (voice, model, instructions, speed)."""
    if req.voice is not None:
        valid_ids = {v["id"] for v in VOICES}
        if req.voice not in valid_ids:
            raise HTTPException(status_code=400, detail=f"Unknown voice: {req.voice}")
        _tts_settings["voice"] = req.voice
    if req.model is not None:
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
