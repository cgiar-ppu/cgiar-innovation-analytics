"""
Voice-to-text transcription route using OpenAI's transcription API.

Accepts audio via multipart upload and returns the transcribed text.
Requires OPENAI_API_KEY environment variable.

Uses gpt-4o-transcribe as the primary model with automatic fallback
to whisper-1 if the primary model rejects the audio format.
"""

import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, HTTPException
from synapsis.config import logger

router = APIRouter()

# Models to try in order. gpt-4o-transcribe is higher quality but stricter
# about audio format/metadata; whisper-1 is more permissive.
_TRANSCRIPTION_MODELS = ["gpt-4o-transcribe", "whisper-1"]

_OPENAI_TRANSCRIPTION_URL = "https://api.openai.com/v1/audio/transcriptions"


def _clean_content_type(raw: str | None) -> str:
    """Extract the base MIME type, stripping codec parameters.

    Browsers set content types like ``audio/webm;codecs=opus`` on
    MediaRecorder output.  The semicolon-delimited codec parameter can
    confuse the OpenAI API's format detection, causing a 400 error.
    This helper returns just ``audio/webm``.
    """
    if not raw:
        return "audio/webm"
    # Take only the part before the first semicolon
    return raw.split(";")[0].strip()


@router.post("/api/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    """Transcribe an audio file using OpenAI's transcription API."""

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="OPENAI_API_KEY environment variable is not set. "
                   "Add it to your shell profile or export it before starting the server.",
        )

    try:
        import httpx
    except ImportError:
        raise HTTPException(status_code=500, detail="httpx is required but not installed")

    # Save uploaded audio to a temp file (OpenAI API needs a file path/name)
    suffix = Path(file.filename or "audio.webm").suffix or ".webm"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    if len(content) < 100:
        os.unlink(tmp_path)
        raise HTTPException(status_code=400, detail="Audio file is too small to transcribe")

    # Clean the content type: strip codec params (e.g. audio/webm;codecs=opus -> audio/webm)
    clean_ct = _clean_content_type(file.content_type)
    filename = file.filename or f"audio{suffix}"

    try:
        logger.info(
            "Transcribing %d bytes of audio (%s, content_type=%s -> %s)",
            len(content), suffix, file.content_type, clean_ct,
        )

        last_error_detail = ""

        for model in _TRANSCRIPTION_MODELS:
            async with httpx.AsyncClient(timeout=60.0) as client:
                with open(tmp_path, "rb") as audio_file:
                    resp = await client.post(
                        _OPENAI_TRANSCRIPTION_URL,
                        headers={"Authorization": f"Bearer {api_key}"},
                        data={"model": model},
                        files={"file": (filename, audio_file, clean_ct)},
                    )

            if resp.status_code == 200:
                result = resp.json()
                text = result.get("text", "").strip()
                logger.info("Transcription complete (%s): %d chars", model, len(text))
                return {"text": text}

            # Parse OpenAI error for better diagnostics
            try:
                err_body = resp.json()
                err_msg = err_body.get("error", {}).get("message", resp.text)
            except Exception:
                err_msg = resp.text

            last_error_detail = f"{model}: {resp.status_code} - {err_msg}"
            logger.warning(
                "OpenAI transcription failed with %s: %s %s",
                model, resp.status_code, err_msg,
            )

            # Only fall back on 400 (format/validation errors).
            # For 401/403/429/500+ errors, don't retry with a different model.
            if resp.status_code != 400:
                break

        logger.error("All transcription models failed. Last: %s", last_error_detail)
        raise HTTPException(
            status_code=502,
            detail=f"Transcription failed: {last_error_detail}",
        )

    finally:
        os.unlink(tmp_path)
