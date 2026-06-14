"""
File upload and download endpoints.

- POST /api/upload         — Upload a file to workspace/uploads/
- GET  /api/files          — List all workspace files (excluding dotfiles)
- GET  /api/files/{path}   — Download a specific file
"""

from pathlib import PurePosixPath

from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import FileResponse

from synapsis.config import WORKSPACE, logger

router = APIRouter(prefix="/api", tags=["files"])


@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """Upload a file to the workspace uploads directory."""
    if not file.filename:
        raise HTTPException(400, "Filename is required")
    # Sanitize: strip path components, prevent directory traversal
    safe_name = PurePosixPath(file.filename).name
    if not safe_name or safe_name.startswith("."):
        raise HTTPException(400, "Invalid filename")

    upload_dir = WORKSPACE / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest = upload_dir / safe_name
    content = await file.read()
    dest.write_bytes(content)
    logger.info("Uploaded %s (%d bytes)", dest, len(content))
    return {"path": str(dest), "size": len(content)}


@router.get("/files")
async def list_files():
    """List all non-hidden files in the workspace recursively."""
    files = []
    for p in sorted(WORKSPACE.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(WORKSPACE)
        # Skip dotfiles and hidden directories
        if any(part.startswith(".") for part in rel.parts):
            continue
        files.append({
            "name": str(rel),
            "size": p.stat().st_size,
            "modified": p.stat().st_mtime,
        })
    return {"files": files}


# Image/inline-renderable extensions are served WITHOUT a forced-download
# Content-Disposition so the chat UI can display them inline via <img> tags.
_INLINE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}


@router.get("/files/{filename:path}")
async def download_file(filename: str):
    """Serve a file from the workspace by relative path.

    Images are served inline (so the chat UI can render them in <img> tags);
    all other file types are served as downloads.
    """
    path = (WORKSPACE / filename).resolve()
    workspace_resolved = WORKSPACE.resolve()
    # Prevent path traversal attacks
    if not str(path).startswith(str(workspace_resolved)):
        raise HTTPException(403, "Access denied: path outside workspace")
    if not path.exists() or not path.is_file():
        raise HTTPException(404, "File not found")
    if path.suffix.lower() in _INLINE_EXTENSIONS:
        # Inline disposition — browser renders rather than forcing a download.
        return FileResponse(path, content_disposition_type="inline")
    return FileResponse(path, filename=path.name)
