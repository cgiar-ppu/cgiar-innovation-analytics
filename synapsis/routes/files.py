"""
File upload and download endpoints.

- POST /api/upload         — Upload a file to workspace/uploads/
- GET  /api/files          — List all workspace files (excluding dotfiles)
- GET  /api/files/{path}   — Download a specific file

Auth (added 2026-07-20 — see docs/SECURITY-SCOPING-NOTE.md):
Any authenticated user may list/upload/download — the workspace is shared
across all users (consistent with the existing honest scoping limitation;
this is not a new isolation boundary, just closing an unauthenticated-access
gap). ``GET /api/files`` and ``POST /api/upload`` require a Bearer JWT.
``GET /api/files/{path}`` additionally accepts ``?token=`` because plain
``<a href>`` download links (rendered from chat markdown) cannot attach an
Authorization header — the same pattern already used by
``routes/export.py``. In dev-bypass mode (``IA_AUTH_DISABLED=true``, local
macOS default) auth is skipped entirely, matching every other route.
"""

from pathlib import PurePosixPath

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from fastapi.responses import FileResponse

from synapsis.config import WORKSPACE, AUTH_DISABLED, logger
from synapsis.auth.middleware import get_current_user, get_optional_user
from synapsis.auth.tokens import verify_token

router = APIRouter(prefix="/api", tags=["files"])


async def _require_bearer_or_query_token(
    token: str | None, header_user: dict | None
) -> None:
    """Authenticate a download via ``Authorization: Bearer`` OR ``?token=``.

    ``header_user`` is resolved by FastAPI via ``get_optional_user`` (None if
    no/invalid Authorization header). Mirrors ``routes/export.py``'s pattern:
    browsers cannot attach an Authorization header to a plain ``<a href>``/
    ``window.open`` navigation, so the JWT is also accepted as a query param.
    """
    if AUTH_DISABLED or header_user is not None:
        return
    if token and verify_token(token) is not None:
        return
    raise HTTPException(
        status_code=401,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


@router.post("/upload")
async def upload_file(file: UploadFile = File(...), _user: dict = Depends(get_current_user)):
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
async def list_files(_user: dict = Depends(get_current_user)):
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
async def download_file(
    filename: str,
    token: str | None = None,
    header_user: dict | None = Depends(get_optional_user),
):
    """Serve a file from the workspace by relative path.

    Accepts auth via ``Authorization: Bearer`` OR ``?token=`` — plain <a>
    download links can't attach a header, so the query param mirrors the
    export endpoint's pattern (see module docstring).

    Images are served inline (so the chat UI can render them in <img> tags);
    all other file types are served as downloads.
    """
    await _require_bearer_or_query_token(token, header_user)

    path = (WORKSPACE / filename).resolve()
    workspace_resolved = WORKSPACE.resolve()
    # Prevent path traversal attacks (is_relative_to is exact-boundary-safe,
    # unlike a plain str.startswith which would wrongly admit a sibling
    # directory whose name happens to share the same string prefix).
    if path != workspace_resolved and workspace_resolved not in path.parents:
        raise HTTPException(403, "Access denied: path outside workspace")
    if not path.exists() or not path.is_file():
        raise HTTPException(404, "File not found")
    if path.suffix.lower() in _INLINE_EXTENSIONS:
        # Inline disposition — browser renders rather than forcing a download.
        return FileResponse(path, content_disposition_type="inline")
    return FileResponse(path, filename=path.name)
