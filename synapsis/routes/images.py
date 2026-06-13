"""
Image generation and editing routes using OpenAI's gpt-image-2 model.

Provides:
- Image generation from text prompts via OpenAI's Images API (/v1/images/generations)
- Image editing with reference images via OpenAI's Edit API (/v1/images/edits)

Image preprocessing (edit endpoint):
  iPhone/camera photos often use non-standard formats (MPO, HEIC) and very
  high resolutions (5000+ px) that OpenAI rejects. The edit endpoint
  automatically preprocesses input images:
  - Converts non-standard formats (MPO, HEIC, TIFF, BMP) to PNG
  - Resizes images larger than MAX_IMAGE_DIMENSION (2048 px longest side)
  - Converts color modes (CMYK, P, LA, PA, I, F) to RGB/RGBA
  - Preprocessed copies are saved to a temp directory and cleaned up after use

Requires OPENAI_API_KEY environment variable (same key used for TTS/transcribe).
"""

import os
import time
import base64
import tempfile
import shutil
from pathlib import Path
from io import BytesIO

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, Literal

from synapsis.config import logger

router = APIRouter()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_MODEL = "gpt-image-2"
AVAILABLE_MODELS = [
    {"id": "gpt-image-2", "name": "GPT Image 2", "description": "Latest model (April 2026) — highest quality"},
]

AVAILABLE_SIZES = ["1024x1024", "1024x1536", "1536x1024"]
AVAILABLE_QUALITIES = ["low", "medium", "high"]

# ---------------------------------------------------------------------------
# Image preprocessing constants
# ---------------------------------------------------------------------------

# Maximum dimension (longest side) for images sent to OpenAI's edit API.
# Images larger than this are resized with LANCZOS downsampling.
# OpenAI's limit is 4 Mpx total; 2048 px keeps us well within budget
# while preserving enough detail for high-quality edits.
MAX_IMAGE_DIMENSION = 2048

# Formats that require conversion to PNG before sending to OpenAI.
# MPO = Multi-Picture Object (iPhone Live Photos / burst shots)
# HEIC/HEIF = Apple's default photo format since iOS 11
# TIFF/BMP = legacy formats not accepted by the edit endpoint
FORMATS_REQUIRING_CONVERSION = {"MPO", "HEIC", "HEIF", "TIFF", "BMP"}

# Color modes that need to be converted to RGB/RGBA for PNG export.
# CMYK = print color space, P = palette, I = 32-bit integer, F = 32-bit float
MODES_REQUIRING_CONVERSION = {"CMYK", "P", "LA", "PA", "I", "F"}


# ---------------------------------------------------------------------------
# Request/response models
# ---------------------------------------------------------------------------

class ImageGenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=32000, description="Text description of the image to generate")
    model: Optional[str] = Field(None, description="Model to use (default: gpt-image-2)")
    size: Optional[Literal["1024x1024", "1024x1536", "1536x1024"]] = Field("1024x1024", description="Image dimensions")
    quality: Optional[Literal["low", "medium", "high"]] = Field("medium", description="Image quality level")
    n: Optional[int] = Field(1, ge=1, le=4, description="Number of images to generate (1-4)")
    background: Optional[Literal["auto", "transparent"]] = Field("auto", description="Background style")
    output_format: Optional[Literal["png", "jpeg"]] = Field("png", description="Output image format")


class GeneratedImage(BaseModel):
    b64_json: str
    index: int


class ImageGenerateResponse(BaseModel):
    images: list[GeneratedImage]
    model: str
    prompt: str
    size: str
    quality: str
    elapsed_seconds: float


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


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/api/images/generate", response_model=ImageGenerateResponse)
async def generate_image(req: ImageGenerateRequest):
    """Generate images from a text prompt using OpenAI's image generation API."""
    api_key = _get_api_key()

    try:
        import httpx
    except ImportError:
        raise HTTPException(status_code=500, detail="httpx is required but not installed")

    model = req.model or DEFAULT_MODEL
    size = req.size or "1024x1024"
    quality = req.quality or "medium"
    n = req.n or 1

    t0 = time.monotonic()
    logger.info(
        "Image generation request: model=%s size=%s quality=%s n=%d prompt_len=%d",
        model, size, quality, n, len(req.prompt),
    )

    payload = {
        "model": model,
        "prompt": req.prompt,
        "size": size,
        "quality": quality,
        "n": n,
    }

    # Add optional parameters
    if req.background and req.background != "auto":
        payload["background"] = req.background
    if req.output_format:
        payload["output_format"] = req.output_format

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/images/generations",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )

            if resp.status_code == 401 or resp.status_code == 403:
                detail = "OpenAI API key is invalid or lacks permissions for image generation."
                try:
                    body = resp.json()
                    if "error" in body:
                        detail = body["error"].get("message", detail)
                except Exception:
                    pass
                logger.error("OpenAI image auth failed: %s", resp.status_code)
                raise HTTPException(status_code=resp.status_code, detail=detail)

            if resp.status_code == 429:
                logger.warning("OpenAI image rate limited")
                raise HTTPException(
                    status_code=429,
                    detail="Rate limit reached. Please wait a moment and try again.",
                )

            if resp.status_code == 400:
                detail = "Invalid request. Please check your prompt and try again."
                try:
                    body = resp.json()
                    if "error" in body:
                        err_msg = body["error"].get("message", "")
                        if "content_policy" in err_msg.lower() or "safety" in err_msg.lower():
                            detail = "This prompt was flagged by OpenAI's content policy. Try rephrasing."
                        else:
                            detail = err_msg or detail
                except Exception:
                    pass
                logger.warning("OpenAI image bad request: %s", detail)
                raise HTTPException(status_code=400, detail=detail)

            if resp.status_code >= 500:
                logger.error("OpenAI image server error: %s", resp.status_code)
                raise HTTPException(
                    status_code=502,
                    detail="OpenAI service error. Please try again later.",
                )

            if resp.status_code != 200:
                logger.error("OpenAI image unexpected status: %s", resp.status_code)
                raise HTTPException(
                    status_code=502,
                    detail=f"Unexpected response from OpenAI: {resp.status_code}",
                )

            data = resp.json()

    except httpx.TimeoutException:
        logger.error("OpenAI image generation timed out")
        raise HTTPException(
            status_code=504,
            detail="Image generation timed out. Try a simpler prompt or lower quality setting.",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("OpenAI image generation failed: %s", str(e))
        raise HTTPException(
            status_code=502,
            detail=f"Failed to connect to OpenAI: {str(e)}",
        )

    elapsed = time.monotonic() - t0
    images = [
        GeneratedImage(b64_json=item["b64_json"], index=i)
        for i, item in enumerate(data.get("data", []))
    ]

    logger.info(
        "Image generation complete: model=%s n=%d elapsed=%.1fs",
        model, len(images), elapsed,
    )

    return ImageGenerateResponse(
        images=images,
        model=model,
        prompt=req.prompt,
        size=size,
        quality=quality,
        elapsed_seconds=round(elapsed, 2),
    )


# ---------------------------------------------------------------------------
# Image Edit — modify existing images using reference images + prompt
# ---------------------------------------------------------------------------

class ImageEditRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=32000, description="Text description of the desired edit")
    image_paths: list[str] = Field(..., min_length=1, max_length=16, description="List of local file paths to reference images (1-16)")
    mask_path: Optional[str] = Field(None, description="Optional mask image path (PNG with alpha channel — transparent areas get edited)")
    model: Optional[str] = Field(None, description="Model to use (default: gpt-image-2)")
    size: Optional[Literal["1024x1024", "1024x1536", "1536x1024"]] = Field("1024x1024", description="Output image dimensions")
    quality: Optional[Literal["low", "medium", "high"]] = Field("medium", description="Image quality level")
    n: Optional[int] = Field(1, ge=1, le=4, description="Number of images to generate (1-4)")


class ImageEditResponse(BaseModel):
    images: list[GeneratedImage]
    model: str
    prompt: str
    size: str
    quality: str
    input_image_count: int
    has_mask: bool
    elapsed_seconds: float


def _preprocess_image(source: Path, temp_dir: Path) -> Path:
    """Preprocess an image for OpenAI's edit API.

    Handles three common issues with user-uploaded photos:

    1. **Non-standard formats** (MPO from iPhone, HEIC, TIFF, BMP):
       OpenAI only accepts PNG, JPG, WebP. We convert to PNG.

    2. **Oversized images** (e.g. 5712x4284 from a modern phone camera):
       Large images cause API errors or timeouts. We resize to fit within
       MAX_IMAGE_DIMENSION (2048 px) on the longest side, preserving aspect ratio.

    3. **Incompatible color modes** (CMYK, palette, 32-bit):
       PNG requires RGB or RGBA. We convert as needed, preserving alpha if present.

    Returns the original path if no preprocessing is needed, or a path to
    a preprocessed copy in temp_dir.
    """
    try:
        from PIL import Image
    except ImportError:
        logger.warning("Pillow not installed — skipping image preprocessing")
        return source

    try:
        img = Image.open(source)
    except Exception as e:
        logger.warning("Cannot open image for preprocessing: %s — %s", source.name, e)
        return source

    needs_conversion = False
    reasons = []

    # Check 1: Non-standard format (MPO, HEIC, etc.)
    fmt = img.format or ""
    if fmt.upper() in FORMATS_REQUIRING_CONVERSION:
        needs_conversion = True
        reasons.append(f"format {fmt} → PNG")

    # Check 2: Oversized dimensions
    max_dim = max(img.size)
    if max_dim > MAX_IMAGE_DIMENSION:
        needs_conversion = True
        reasons.append(f"resize {img.size[0]}x{img.size[1]} → max {MAX_IMAGE_DIMENSION}px")

    # Check 3: Incompatible color mode
    if img.mode in MODES_REQUIRING_CONVERSION:
        needs_conversion = True
        reasons.append(f"mode {img.mode} → RGB")

    if not needs_conversion:
        img.close()
        return source

    # Perform preprocessing
    logger.info(
        "Preprocessing image %s: %s",
        source.name, ", ".join(reasons),
    )

    # Convert color mode
    if img.mode in MODES_REQUIRING_CONVERSION:
        img = img.convert("RGBA" if "A" in img.mode else "RGB")
    elif img.mode not in {"RGB", "RGBA", "L"}:
        img = img.convert("RGB")

    # Resize if needed
    if max_dim > MAX_IMAGE_DIMENSION:
        ratio = MAX_IMAGE_DIMENSION / max_dim
        new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
        img = img.resize(new_size, Image.LANCZOS)

    # Save preprocessed copy
    out_path = temp_dir / f"{source.stem}_preprocessed.png"
    img.save(out_path, "PNG")
    final_w, final_h = img.size
    img.close()

    out_size_mb = out_path.stat().st_size / (1024 * 1024)
    logger.info(
        "Preprocessed %s → %s (%dx%d, %.1f MB)",
        source.name, out_path.name, final_w, final_h, out_size_mb,
    )

    return out_path


def _validate_image_path(path: str) -> Path:
    """Validate that an image path exists and is a supported format."""
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise HTTPException(status_code=400, detail=f"Image file not found: {path}")
    if not p.is_file():
        raise HTTPException(status_code=400, detail=f"Path is not a file: {path}")
    suffix = p.suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported image format '{suffix}' for {p.name}. Must be PNG, JPG, or WebP.",
        )
    size_mb = p.stat().st_size / (1024 * 1024)
    if size_mb > 50:
        raise HTTPException(
            status_code=400,
            detail=f"Image {p.name} is {size_mb:.1f} MB — must be under 50 MB.",
        )
    return p


@router.post("/api/images/edit", response_model=ImageEditResponse)
async def edit_image(req: ImageEditRequest):
    """Edit/modify images using reference images and a text prompt.

    Uses OpenAI's /v1/images/edits endpoint (multipart form data).
    Accepts 1-16 local image paths as reference and produces modified images.
    Optionally accepts a mask image for inpainting (only transparent areas are edited).
    """
    api_key = _get_api_key()

    try:
        import httpx
    except ImportError:
        raise HTTPException(status_code=500, detail="httpx is required but not installed")

    model = req.model or DEFAULT_MODEL
    size = req.size or "1024x1024"
    quality = req.quality or "medium"
    n = req.n or 1

    # Validate all image paths
    image_paths = [_validate_image_path(p) for p in req.image_paths]

    # Validate mask if provided
    mask_path = None
    if req.mask_path:
        mask_path = _validate_image_path(req.mask_path)

    t0 = time.monotonic()
    logger.info(
        "Image edit request: model=%s size=%s quality=%s n=%d images=%d mask=%s prompt_len=%d",
        model, size, quality, n, len(image_paths), bool(mask_path), len(req.prompt),
    )

    # Preprocess images: convert non-standard formats (MPO, HEIC, etc.)
    # and resize oversized images. Preprocessed copies are saved to a
    # temporary directory that gets cleaned up in the finally block.
    temp_dir = Path(tempfile.mkdtemp(prefix="synapsis_img_edit_"))
    processed_paths = []
    try:
        for img_path in image_paths:
            processed = _preprocess_image(img_path, temp_dir)
            processed_paths.append(processed)

        if mask_path:
            mask_path = _preprocess_image(mask_path, temp_dir)
    except Exception as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        logger.error("Image preprocessing failed: %s", str(e))
        raise HTTPException(status_code=400, detail=f"Image preprocessing failed: {str(e)}")

    # Build multipart form data for OpenAI's /v1/images/edits endpoint.
    # The API accepts images as file uploads via multipart/form-data.
    # For multiple images, each is sent as a separate 'image[]' field.
    files = []
    opened_files = []
    try:
        # Add image files (using preprocessed paths)
        for img_path in processed_paths:
            f = open(img_path, "rb")
            opened_files.append(f)
            # OpenAI expects 'image[]' for multiple images, 'image' for single
            field_name = "image[]" if len(processed_paths) > 1 else "image"
            files.append((field_name, (img_path.name, f, f"image/{img_path.suffix.lstrip('.').replace('jpg', 'jpeg')}")))

        # Add mask if provided
        if mask_path:
            mf = open(mask_path, "rb")
            opened_files.append(mf)
            files.append(("mask", (mask_path.name, mf, "image/png")))

        # Form data fields (sent alongside files)
        data = {
            "model": model,
            "prompt": req.prompt,
            "size": size,
            "quality": quality,
            "n": str(n),
        }

        try:
            async with httpx.AsyncClient(timeout=180.0) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/images/edits",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                    },
                    data=data,
                    files=files,
                )

                if resp.status_code == 401 or resp.status_code == 403:
                    detail = "OpenAI API key is invalid or lacks permissions for image editing."
                    try:
                        body = resp.json()
                        if "error" in body:
                            detail = body["error"].get("message", detail)
                    except Exception:
                        pass
                    logger.error("OpenAI image edit auth failed: %s", resp.status_code)
                    raise HTTPException(status_code=resp.status_code, detail=detail)

                if resp.status_code == 429:
                    logger.warning("OpenAI image edit rate limited")
                    raise HTTPException(
                        status_code=429,
                        detail="Rate limit reached. Please wait a moment and try again.",
                    )

                if resp.status_code == 400:
                    detail = "Invalid edit request. Check your prompt, images, and mask."
                    try:
                        body = resp.json()
                        if "error" in body:
                            err_msg = body["error"].get("message", "")
                            if "content_policy" in err_msg.lower() or "safety" in err_msg.lower():
                                detail = "This edit was flagged by OpenAI's content policy. Try rephrasing."
                            else:
                                detail = err_msg or detail
                    except Exception:
                        pass
                    logger.warning("OpenAI image edit bad request: %s", detail)
                    raise HTTPException(status_code=400, detail=detail)

                if resp.status_code >= 500:
                    logger.error("OpenAI image edit server error: %s", resp.status_code)
                    raise HTTPException(
                        status_code=502,
                        detail="OpenAI service error. Please try again later.",
                    )

                if resp.status_code != 200:
                    logger.error("OpenAI image edit unexpected status: %s", resp.status_code)
                    raise HTTPException(
                        status_code=502,
                        detail=f"Unexpected response from OpenAI: {resp.status_code}",
                    )

                response_data = resp.json()

        except httpx.TimeoutException:
            logger.error("OpenAI image edit timed out")
            raise HTTPException(
                status_code=504,
                detail="Image editing timed out. Try 'medium' or 'low' quality, "
                       "fewer reference images, or a simpler prompt.",
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error("OpenAI image edit failed: %s", str(e))
            raise HTTPException(
                status_code=502,
                detail=f"Failed to connect to OpenAI: {str(e)}",
            )

    finally:
        # Always close opened file handles and clean up temp directory
        for f in opened_files:
            f.close()
        shutil.rmtree(temp_dir, ignore_errors=True)

    elapsed = time.monotonic() - t0
    images = [
        GeneratedImage(b64_json=item["b64_json"], index=i)
        for i, item in enumerate(response_data.get("data", []))
    ]

    logger.info(
        "Image edit complete: model=%s n=%d input_images=%d elapsed=%.1fs",
        model, len(images), len(image_paths), elapsed,
    )

    return ImageEditResponse(
        images=images,
        model=model,
        prompt=req.prompt,
        size=size,
        quality=quality,
        input_image_count=len(image_paths),
        has_mask=bool(mask_path),
        elapsed_seconds=round(elapsed, 2),
    )


# ---------------------------------------------------------------------------
# Model & config discovery
# ---------------------------------------------------------------------------

@router.get("/api/images/models")
async def list_image_models():
    """Return available image generation models and configuration options."""
    return {
        "models": AVAILABLE_MODELS,
        "sizes": AVAILABLE_SIZES,
        "qualities": AVAILABLE_QUALITIES,
        "defaults": {
            "model": DEFAULT_MODEL,
            "size": "1024x1024",
            "quality": "medium",
            "n": 1,
            "background": "auto",
            "output_format": "png",
        },
        "edit_limits": {
            "max_images": 16,
            "max_image_size_mb": 50,
            "supported_formats": ["png", "jpg", "jpeg", "webp"],
        },
    }
