"""
File upload and download endpoints.

- POST /api/upload         — Upload a file to the caller's own uploads area
- GET  /api/files          — List the files the caller may open
- GET  /api/files/{path}   — Download a specific file

Auth (added 2026-07-20): ``GET /api/files`` and ``POST /api/upload`` require a
Bearer JWT. ``GET /api/files/{path}`` additionally accepts ``?token=`` because
plain ``<a href>`` download links (rendered from chat markdown) cannot attach
an Authorization header — the same pattern already used by
``routes/export.py``. In dev-bypass mode (``IA_AUTH_DISABLED=true``, local
macOS default) auth is skipped and the caller is the local admin dev user.

Per-owner files (2026-09-26, review L4-03 / L6-09; see synapsis/user_files.py):
* uploads go to ``uploads/u/<owner>/`` and agent-created files to
  ``outputs/u/<owner>/<random token>/``;
* a caller lists and downloads only their OWN areas plus the chat exports of
  their own sessions (every role — admin rights never widen access to other
  people's material, Jose 2026-09-14);
* legacy shared files created before this change (flat ``outputs/``,
  ``uploads/`` …) are administrator-only;
* hidden paths (``.synapsis/chat.db`` etc.) are never served;
* nothing user-supplied is rendered inline except raster images — SVG is
  always a download (stored-XSS vector, review L1-05).
"""

import os
from pathlib import Path, PurePosixPath

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from fastapi.responses import FileResponse

from synapsis.config import WORKSPACE, AUTH_DISABLED, logger
from synapsis.auth.middleware import get_current_user, get_optional_user, resolve_user_id, resolve_role
from synapsis.user_files import OWNER_AREAS, OWNER_DIR, can_access, owner_area, owner_key
from synapsis.database import get_db
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


async def _owned_chat_export(path, user):
    """Chat export files retain the same owner check as /api/export."""
    async with get_db() as db:
        cursor = await db.execute("SELECT session_id FROM sessions WHERE user_id = ?", (resolve_user_id(user),))
        ids = [row[0] for row in await cursor.fetchall()]
    return any(path.stem.endswith("_" + sid) or path.stem.endswith("_" + sid + "_temp") for sid in ids)


@router.post("/upload")
async def upload_file(file: UploadFile = File(...), _user: dict = Depends(get_current_user)):
    """Upload a file into the caller's own uploads area."""
    if not file.filename:
        raise HTTPException(400, "Filename is required")
    # Sanitize: strip path components, prevent directory traversal
    safe_name = PurePosixPath(file.filename).name
    if not safe_name or safe_name.startswith("."):
        raise HTTPException(400, "Invalid filename")

    upload_dir = owner_area("uploads", resolve_user_id(_user), WORKSPACE)
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest = upload_dir / safe_name
    content = await file.read()
    dest.write_bytes(content)
    logger.info("Uploaded %s (%d bytes)", safe_name, len(content))
    return {"path": str(dest), "size": len(content)}


def _walk_visible(root: Path, user_id: str, role: str):
    """Yield workspace files the caller may see, pruning foreign/hidden dirs."""
    root_resolved = root.resolve()
    own = owner_key(user_id)
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        rel_dir = Path(dirpath).relative_to(root)
        parts = rel_dir.parts
        keep = []
        for d in dirnames:
            if d.startswith("."):
                continue
            # Inside <area>/u/ only the caller's own folder is walked.
            if len(parts) == 2 and parts[0] in OWNER_AREAS and parts[1] == OWNER_DIR and d != own:
                continue
            keep.append(d)
        dirnames[:] = keep
        for name in filenames:
            if name.startswith("."):
                continue
            p = Path(dirpath) / name
            if p.is_symlink() or not p.is_file():
                continue
            try:
                if not p.resolve().is_relative_to(root_resolved):
                    continue
            except OSError:
                continue
            yield p, p.relative_to(root)


@router.get("/files")
async def list_files(_user: dict = Depends(get_current_user)):
    """List the files the caller may open (own areas + own chat exports)."""
    user_id, role = resolve_user_id(_user), resolve_role(_user)
    files = []
    for p, rel in sorted(_walk_visible(WORKSPACE, user_id, role), key=lambda t: str(t[1])):
        if rel.parts[0] == "exports":
            if not await _owned_chat_export(p, _user):
                continue
        elif not can_access(PurePosixPath(*rel.parts), user_id, role):
            continue
        st = p.stat()
        files.append({"name": str(rel), "size": st.st_size, "modified": st.st_mtime})
    return {"files": files}


# Raster images are served WITHOUT a forced-download Content-Disposition so the
# chat UI can display them inline via <img> tags. SVG is NOT inline: an SVG can
# carry script and would run on the app origin (review L1-05).
_INLINE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


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
    relative = path.relative_to(workspace_resolved)
    if any(part.startswith(".") for part in PurePosixPath(filename).parts + relative.parts):
        raise HTTPException(404, "File not found")
    user = header_user or (verify_token(token) if token else None)
    if relative.parts and relative.parts[0] == "exports":
        if not await _owned_chat_export(path, user):
            raise HTTPException(404, "File not found")
    elif not can_access(PurePosixPath(*relative.parts), resolve_user_id(user), resolve_role(user)):
        # Someone else's file, a legacy shared file (admin-only) or the bare
        # workspace: indistinguishable from "missing" for the caller.
        raise HTTPException(404, "File not found")
    if not path.exists() or not path.is_file():
        raise HTTPException(404, "File not found")
    if path.suffix.lower() in _INLINE_EXTENSIONS:
        # Inline disposition — browser renders rather than forcing a download.
        return FileResponse(
            path,
            filename=path.name,
            content_disposition_type="inline",
            headers={"Content-Security-Policy": "default-src 'none'; sandbox"},
        )
    return FileResponse(path, filename=path.name)
