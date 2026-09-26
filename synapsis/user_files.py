"""
Per-owner file areas for uploads and agent-created files (review L4-03/L6-09).

Before 2026-09-26 every upload landed in ``WORKSPACE/uploads/`` and every
agent-made file in ``WORKSPACE/outputs/``, both shared by all users: the Files
tab listed everyone's files and any signed-in user could download them.

Layout now::

    WORKSPACE/uploads/u/<owner-key>/<name>                 user uploads
    WORKSPACE/outputs/u/<owner-key>/<token>/<file>         agent-created files

* ``<owner-key>`` is a stable, opaque key derived from the owning ``user_id``
  (never the raw id / e-mail, which would leak identities through paths).
* ``<token>`` is a fresh 128-bit random value per created file, so file URLs are
  unguessable even for someone who knows an owner key.
* Access is decided by :func:`can_access`: a caller may only read inside their
  own ``u/<owner-key>/`` areas. Files outside any owner area (legacy flat
  ``outputs/`` / ``uploads/`` files created before this change, and anything
  else in the workspace) are administrator-only; hidden paths are never served.

The same rules drive the HTTP routes (``routes/files.py``) and the agent's
path-confinement hook (``hooks/sandbox.py``).
"""

from __future__ import annotations

import hashlib
import re
import secrets
from pathlib import Path, PurePosixPath

#: Top-level workspace areas that hold per-owner sub-areas.
OWNER_AREAS: tuple[str, ...] = ("uploads", "outputs")

#: Directory under each area that holds the per-owner folders.
OWNER_DIR = "u"


def _workspace() -> Path:
    # Read at call time: tests (and routes/files.py) patch WORKSPACE.
    from synapsis import config

    return Path(config.WORKSPACE)


def owner_key(user_id: str | None) -> str:
    """Opaque, stable folder key for *user_id* (24 hex chars)."""
    raw = f"cgiar-ia-owner-v1:{user_id or ''}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:24]


def owner_area(area: str, user_id: str | None, workspace: Path | None = None) -> Path:
    """Absolute path of *user_id*'s folder in *area* (``uploads``/``outputs``)."""
    if area not in OWNER_AREAS:
        raise ValueError(f"unknown owner area {area!r}")
    root = Path(workspace) if workspace is not None else _workspace()
    return root / area / OWNER_DIR / owner_key(user_id)


def safe_stem(name: str, default: str = "document", max_len: int = 60) -> str:
    """Filesystem-safe, readable stem (letters, digits, ``-`` and ``_``)."""
    stem = re.sub(r"[^A-Za-z0-9_-]+", "-", (name or "").strip()).strip("-_")
    return (stem or default)[:max_len]


def new_output_path(user_id: str | None, stem: str, ext: str, workspace: Path | None = None) -> Path:
    """Create ``outputs/u/<owner>/<token>/`` and return a file path inside it.

    The directory is created; the file is not.
    """
    token = secrets.token_hex(16)
    folder = owner_area("outputs", user_id, workspace) / token
    folder.mkdir(parents=True, exist_ok=True)
    ext = ext if ext.startswith(".") else f".{ext}"
    return folder / f"{safe_stem(stem)}{ext}"


def new_output_dir(user_id: str | None, workspace: Path | None = None) -> Path:
    """Create and return a fresh unguessable ``outputs/u/<owner>/<token>/`` dir."""
    folder = owner_area("outputs", user_id, workspace) / secrets.token_hex(16)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def is_hidden(parts: tuple[str, ...]) -> bool:
    return any(p.startswith(".") for p in parts)


def owner_of(relative: PurePosixPath | Path | str) -> str | None:
    """Owner key of a workspace-relative path, or ``None`` if not in an owner area."""
    parts = PurePosixPath(str(relative)).parts
    if len(parts) >= 3 and parts[0] in OWNER_AREAS and parts[1] == OWNER_DIR:
        return parts[2]
    return None


def can_access(relative: PurePosixPath | Path | str, user_id: str | None, role: str | None) -> bool:
    """May *user_id* (with verified *role*) read this workspace-relative path?

    * hidden paths (any ``.``-prefixed component): never;
    * inside ``uploads/u/<k>/`` or ``outputs/u/<k>/``: only the owner of ``<k>``
      (administrators included only for their OWN key — Jose's 2026-09-14
      ruling: admin rights never widen access to other people's material);
    * chat exports (``exports/``): decided by the caller (``routes/files.py``
      keeps its session-ownership check);
    * anything else (legacy shared files): administrators only.
    """
    parts = PurePosixPath(str(relative)).parts
    if not parts or is_hidden(parts):
        return False
    key = owner_of(relative)
    if key is not None:
        return bool(user_id) and key == owner_key(user_id)
    if parts[0] in OWNER_AREAS and len(parts) >= 2 and parts[1] == OWNER_DIR:
        return False  # the bare ``uploads/u`` / ``outputs/u`` folders
    return role == "admin"

