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

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from synapsis import ai_endpoint
from synapsis.auth.middleware import get_current_user
from synapsis.config import logger

router = APIRouter(dependencies=[Depends(get_current_user)])
# Models to try in order. gpt-4o-transcribe is higher quality but stricter
# about audio format/metadata; whisper-1 is more permissive.
_TRANSCRIPTION_MODELS = ["gpt-4o-transcribe", "whisper-1"]



def _transcription_targets() -> list[tuple[str, str, dict]]:
    """(model, url, extra form fields) in fallback order for the configured endpoint.

    Azure serves audio only on the deployments path (not /openai/v1); the deployment name is the model.
    ``IA_TRANSCRIBE_MODELS`` (comma-separated deployment/model names) overrides the default order.
    """
    configured = [m.strip() for m in (os.getenv("IA_TRANSCRIBE_MODELS") or "").split(",") if m.strip()]
    if ai_endpoint.is_azure():
        return [(m, ai_endpoint.azure_transcription_url(m), {}) for m in (configured or ["gpt-4o-transcribe"])]
    return [(m, ai_endpoint.v1("audio/transcriptions"), {"model": m}) for m in (configured or _TRANSCRIPTION_MODELS)]

#: OpenAI's own upload limit; larger bodies are refused before any call
#: (review L6-07: the upload used to be read whole with no cap).
MAX_AUDIO_BYTES = 25 * 1024 * 1024


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
        raise HTTPException(status_code=503, detail="Dictation is not configured on this server.")

    try:
        import httpx
    except ImportError:
        raise HTTPException(status_code=500, detail="httpx is required but not installed")

    # Save uploaded audio to a temp file (OpenAI API needs a file path/name)
    suffix = Path(file.filename or "audio.webm").suffix or ".webm"
    if not suffix[1:].isalnum() or len(suffix) > 6:
        suffix = ".webm"
    content = await file.read(MAX_AUDIO_BYTES + 1)
    if len(content) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="The recording is too long to transcribe (25 MB maximum).")
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
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

        for model, url, form in _transcription_targets():
            async with httpx.AsyncClient(timeout=60.0) as client:
                with open(tmp_path, "rb") as audio_file:
                    resp = await client.post(
                        url,
                        headers=ai_endpoint.auth_headers(api_key),
                        data=form,
                        files={"file": (filename, audio_file, clean_ct)},
                    )

            if resp.status_code == 200:
                result = resp.json()
                text = result.get("text", "").strip()
                logger.info("Transcription complete (%s): %d chars", model, len(text))
                return {"text": text}

            # Status and error type only: the provider message can echo a
            # masked key fragment (review L6-07), so it is neither logged nor
            # returned to the browser.
            try:
                err_type = str(resp.json().get("error", {}).get("type") or "")[:60]
            except Exception:
                err_type = ""

            last_error_detail = f"{model}: provider status {resp.status_code}"
            logger.warning(
                "OpenAI transcription failed with %s: provider_status=%s type=%s",
                model, resp.status_code, err_type,
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
