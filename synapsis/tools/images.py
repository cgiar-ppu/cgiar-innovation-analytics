"""
Image generation and editing MCP tools — lets the orchestrator agent
generate images from text prompts and edit/modify existing images using
reference photos during chat conversations.

Tools:
- image_generate: Create images from scratch via text prompt.
- image_edit: Modify existing images using reference photos + text prompt.
  Supports up to 16 reference images and optional masks for inpainting.
  Automatic preprocessing handles iPhone/camera photos (MPO, HEIC, oversized).

Both tools call internal /api/images/* endpoints (which proxy to OpenAI's
gpt-image-2 model), save results to the workspace, and return file paths.
"""

import os
import time
import base64
from pathlib import Path
from typing import Any

from claude_agent_sdk import tool
from synapsis.config import logger, WORKSPACE
from synapsis.utils.responses import error_response, success_response


@tool(
    "image_generate",
    "Generate an image from a text prompt using OpenAI's gpt-image-2 model. "
    "The image is saved to the workspace and the file path is returned. "
    "Use this when the user asks you to create, generate, draw, or design "
    "an image, illustration, diagram, logo, icon, or any visual content. "
    "Supports sizes: 1024x1024 (square), 1024x1536 (portrait), 1536x1024 (landscape). "
    "Supports qualities: low (~$0.01, ~20s), medium (~$0.05, ~45s), high (~$0.19, ~2min). "
    "Default is medium quality, 1024x1024. Returns the saved file path.",
    {
        "prompt": str,
        "size": str,
        "quality": str,
        "filename": str,
        "background": str,
    },
)
async def image_generate(args: dict[str, Any]) -> dict[str, Any]:
    """Generate an image and save it to the workspace."""

    prompt = args.get("prompt", "").strip()
    if not prompt:
        return error_response("Error: 'prompt' is required. Describe the image you want to generate.")

    size = args.get("size", "1024x1024")
    quality = args.get("quality", "medium")
    filename = args.get("filename", "")
    background = args.get("background", "auto")

    # Validate size
    valid_sizes = {"1024x1024", "1024x1536", "1536x1024"}
    if size not in valid_sizes:
        return error_response(
            f"Error: Invalid size '{size}'. Must be one of: {', '.join(sorted(valid_sizes))}"
        )

    # Validate quality
    valid_qualities = {"low", "medium", "high"}
    if quality not in valid_qualities:
        return error_response(
            f"Error: Invalid quality '{quality}'. Must be one of: {', '.join(sorted(valid_qualities))}"
        )

    # Generate filename if not provided
    if not filename:
        timestamp = int(time.time())
        # Create a short slug from the prompt
        slug = prompt[:40].lower()
        slug = "".join(c if c.isalnum() or c == " " else "" for c in slug)
        slug = slug.strip().replace(" ", "_")
        filename = f"generated_{slug}_{timestamp}.png"

    # Ensure .png extension
    if not filename.lower().endswith((".png", ".jpeg", ".jpg")):
        filename += ".png"

    # Call the internal API endpoint
    try:
        import httpx
    except ImportError:
        return error_response("Error: httpx is required but not installed.")

    from synapsis.config import PORT

    logger.info(
        "MCP image_generate: prompt_len=%d size=%s quality=%s",
        len(prompt), size, quality,
    )

    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            resp = await client.post(
                f"http://localhost:{PORT}/api/images/generate",
                json={
                    "prompt": prompt,
                    "size": size,
                    "quality": quality,
                    "n": 1,
                    "background": background,
                    "output_format": "png",
                },
            )

            if resp.status_code != 200:
                try:
                    detail = resp.json().get("detail", f"HTTP {resp.status_code}")
                except Exception:
                    detail = f"HTTP {resp.status_code}"
                return error_response(f"Image generation failed: {detail}")

            data = resp.json()

    except httpx.TimeoutException:
        return error_response(
            "Image generation timed out. Try 'medium' or 'low' quality, "
            "or a simpler prompt."
        )
    except Exception as e:
        logger.error("MCP image_generate failed: %s", str(e))
        return error_response(f"Image generation failed: {str(e)}")

    # Save image to workspace
    images = data.get("images", [])
    if not images:
        return error_response("Image generation returned no images.")

    output_dir = Path(WORKSPACE) / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / filename

    try:
        image_bytes = base64.b64decode(images[0]["b64_json"])
        output_path.write_bytes(image_bytes)
    except Exception as e:
        return error_response(f"Failed to save image: {str(e)}")

    elapsed = data.get("elapsed_seconds", 0)
    model = data.get("model", "gpt-image-2")
    file_size_kb = len(image_bytes) / 1024

    logger.info(
        "MCP image_generate saved: %s (%.0f KB, %.1fs)",
        output_path, file_size_kb, elapsed,
    )

    msg = (
        f"Image generated and saved successfully.\n\n"
        f"**File:** `{output_path}`\n"
        f"**Model:** {model}\n"
        f"**Size:** {size} | **Quality:** {quality}\n"
        f"**Generation time:** {elapsed}s | **File size:** {file_size_kb:.0f} KB\n\n"
        f"**Prompt:** {prompt}"
    )
    return success_response(msg)


@tool(
    "image_edit",
    "Edit or modify existing images using reference photos and a text prompt, "
    "powered by OpenAI's gpt-image-2 model. This tool takes one or more local "
    "image file paths as input references and produces a new modified image based "
    "on the text prompt. "
    "\n\n"
    "USE CASES: age progression/regression of people in photos, style transfer, "
    "combining elements from multiple photos, changing backgrounds or settings, "
    "adding/removing objects, seasonal or time-of-day changes, artistic "
    "reinterpretations of existing photos, product mockups from reference images, "
    "inpainting (editing only specific areas using a mask). "
    "\n\n"
    "PARAMETERS:\n"
    "- prompt (required): Describe the desired edit in detail. Be specific about "
    "what to change and what to preserve from the reference images.\n"
    "- image_paths (required): JSON array of absolute file paths to reference images. "
    "Accepts 1-16 images. Supported formats: PNG, JPG, JPEG, WebP. Max 50MB each. "
    "Example: [\"/Users/smithai/workspace/uploads/photo1.jpg\", \"/Users/smithai/workspace/uploads/photo2.jpg\"]\n"
    "- mask_path (optional): Path to a PNG mask image with alpha channel. "
    "Fully transparent areas (alpha=0) indicate where the image should be edited. "
    "Only applies to the first image. Use for targeted inpainting.\n"
    "- size (optional): Output dimensions — 1024x1024 (square), 1024x1536 (portrait), "
    "1536x1024 (landscape). Default: 1024x1024.\n"
    "- quality (optional): low (~$0.02, ~20s), medium (~$0.07, ~50s), high (~$0.25, ~2min). "
    "Default: medium.\n"
    "- filename (optional): Output filename (without extension). Default: auto-generated.\n\n"
    "IMPORTANT RULES:\n"
    "- The image_paths parameter must be a JSON array of strings, even for a "
    "single image. Always use absolute paths. Files in uploads/ are at "
    "~/workspace/uploads/.\n"
    "- AUTOMATIC PREPROCESSING: The backend automatically handles iPhone/camera "
    "photos. You do NOT need to manually convert or resize images before calling "
    "this tool. The following are handled transparently:\n"
    "  * MPO format (iPhone Live Photos) → converted to PNG\n"
    "  * HEIC/HEIF format (Apple default) → converted to PNG\n"
    "  * TIFF, BMP → converted to PNG\n"
    "  * Oversized images (>2048px longest side) → resized with LANCZOS\n"
    "  * Non-RGB color modes (CMYK, palette) → converted to RGB/RGBA\n"
    "- Just pass the original uploaded file paths directly — preprocessing is automatic.\n"
    "- If the edit fails with a format/mode error, it means Pillow could not open "
    "the file. Ask the user to re-upload in JPG or PNG format.",
    {
        "prompt": str,
        "image_paths": str,
        "mask_path": str,
        "size": str,
        "quality": str,
        "filename": str,
    },
)
async def image_edit(args: dict[str, Any]) -> dict[str, Any]:
    """Edit/modify existing images using reference photos and a prompt."""

    import json as json_module

    prompt = args.get("prompt", "").strip()
    if not prompt:
        return error_response("Error: 'prompt' is required. Describe the desired edit.")

    image_paths_raw = args.get("image_paths", "").strip()
    if not image_paths_raw:
        return error_response(
            "Error: 'image_paths' is required. Provide a JSON array of file paths "
            "to reference images, e.g. [\"/path/to/photo.jpg\"]"
        )

    # Parse image_paths — accept JSON array or comma-separated
    try:
        image_paths = json_module.loads(image_paths_raw)
        if isinstance(image_paths, str):
            image_paths = [image_paths]
        if not isinstance(image_paths, list):
            raise ValueError("Must be a list")
    except (json_module.JSONDecodeError, ValueError):
        # Try comma-separated fallback
        image_paths = [p.strip() for p in image_paths_raw.split(",") if p.strip()]

    if not image_paths:
        return error_response("Error: No valid image paths provided.")

    if len(image_paths) > 16:
        return error_response("Error: Maximum 16 reference images allowed.")

    # Validate all paths exist
    for p in image_paths:
        resolved = Path(p).expanduser().resolve()
        if not resolved.exists():
            return error_response(f"Error: Image file not found: {p}")
        if not resolved.is_file():
            return error_response(f"Error: Path is not a file: {p}")

    mask_path = args.get("mask_path", "").strip() or None
    if mask_path:
        mask_resolved = Path(mask_path).expanduser().resolve()
        if not mask_resolved.exists():
            return error_response(f"Error: Mask file not found: {mask_path}")

    size = args.get("size", "1024x1024")
    quality = args.get("quality", "medium")
    filename = args.get("filename", "")

    # Validate size
    valid_sizes = {"1024x1024", "1024x1536", "1536x1024"}
    if size not in valid_sizes:
        return error_response(
            f"Error: Invalid size '{size}'. Must be one of: {', '.join(sorted(valid_sizes))}"
        )

    # Validate quality
    valid_qualities = {"low", "medium", "high"}
    if quality not in valid_qualities:
        return error_response(
            f"Error: Invalid quality '{quality}'. Must be one of: {', '.join(sorted(valid_qualities))}"
        )

    # Generate filename if not provided
    if not filename:
        timestamp = int(time.time())
        slug = prompt[:30].lower()
        slug = "".join(c if c.isalnum() or c == " " else "" for c in slug)
        slug = slug.strip().replace(" ", "_")
        filename = f"edited_{slug}_{timestamp}.png"

    # Ensure .png extension
    if not filename.lower().endswith((".png", ".jpeg", ".jpg")):
        filename += ".png"

    # Call the internal API endpoint
    try:
        import httpx
    except ImportError:
        return error_response("Error: httpx is required but not installed.")

    from synapsis.config import PORT

    logger.info(
        "MCP image_edit: prompt_len=%d images=%d mask=%s size=%s quality=%s",
        len(prompt), len(image_paths), bool(mask_path), size, quality,
    )

    try:
        async with httpx.AsyncClient(timeout=240.0) as client:
            payload = {
                "prompt": prompt,
                "image_paths": image_paths,
                "size": size,
                "quality": quality,
                "n": 1,
            }
            if mask_path:
                payload["mask_path"] = mask_path

            resp = await client.post(
                f"http://localhost:{PORT}/api/images/edit",
                json=payload,
            )

            if resp.status_code != 200:
                try:
                    detail = resp.json().get("detail", f"HTTP {resp.status_code}")
                except Exception:
                    detail = f"HTTP {resp.status_code}"
                return error_response(f"Image editing failed: {detail}")

            data = resp.json()

    except httpx.TimeoutException:
        return error_response(
            "Image editing timed out. Try 'medium' or 'low' quality, "
            "fewer reference images, or a simpler prompt."
        )
    except Exception as e:
        logger.error("MCP image_edit failed: %s", str(e))
        return error_response(f"Image editing failed: {str(e)}")

    # Save image to workspace
    images = data.get("images", [])
    if not images:
        return error_response("Image editing returned no images.")

    output_dir = Path(WORKSPACE) / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / filename

    try:
        image_bytes = base64.b64decode(images[0]["b64_json"])
        output_path.write_bytes(image_bytes)
    except Exception as e:
        return error_response(f"Failed to save edited image: {str(e)}")

    elapsed = data.get("elapsed_seconds", 0)
    model = data.get("model", "gpt-image-2")
    file_size_kb = len(image_bytes) / 1024
    input_count = data.get("input_image_count", len(image_paths))
    has_mask = data.get("has_mask", bool(mask_path))

    logger.info(
        "MCP image_edit saved: %s (%.0f KB, %.1fs, %d refs)",
        output_path, file_size_kb, elapsed, input_count,
    )

    # Build descriptive paths list for the response
    paths_display = "\n".join(f"  - `{p}`" for p in image_paths)

    msg = (
        f"Image edited and saved successfully.\n\n"
        f"**Output file:** `{output_path}`\n"
        f"**Model:** {model}\n"
        f"**Size:** {size} | **Quality:** {quality}\n"
        f"**Reference images ({input_count}):**\n{paths_display}\n"
        f"{'**Mask:** `' + str(mask_path) + '`' + chr(10) if has_mask else ''}"
        f"**Edit time:** {elapsed}s | **File size:** {file_size_kb:.0f} KB\n\n"
        f"**Prompt:** {prompt}"
    )
    return success_response(msg)
