"""
prms_snapshot.py — single source of truth for WHICH PRMS snapshot the app reads.

Why this exists
---------------
The PRMS SQLite copy used to be a fixed, dated file (June 2026). Since
2026-09-07 the snapshot refreshes itself daily (skill ``ai--prms-data-refresh``):
the newest *verified* SQLite is always the symlink
``~/workspace/coding/PRMSDB/current`` and its metadata lives next to it in
``LATEST.json``. Every place in the app that used to hard-code a path or a
"June 13 2026" sentence now asks this module instead, so the UI, the agent's
system prompt and every export footer state the snapshot they actually used.

Resolution order for the database path
--------------------------------------
1. ``PRMS_DB_PATH`` environment variable (Docker sets ``/app/data/prdb.sqlite``;
   a developer can pin the June baseline for a comparison run).
2. ``$PRMS_DB_ROOT/current`` (default root ``/Users/smithai/workspace/coding/PRMSDB``).

Resolution order for the snapshot metadata
------------------------------------------
1. ``$PRMS_DB_ROOT/LATEST.json`` — but ONLY when its ``sqlite`` entry resolves to
   the same real file as the path we are reading. If someone pins a different
   file we must not claim LATEST.json's date for it.
2. The database itself: ``SELECT COUNT(*), MAX(last_updated_date) FROM result``
   (read-only URI connection). The extraction date is then inferred from the
   folder/file name (``fresh_20260907`` / ``fresh_13June2026``) or, failing that,
   the file's mtime. This is the path taken inside the production container,
   where LATEST.json does not exist.

The module is stdlib-only and import-cheap. Results are cached for a short TTL
keyed on the real file (path, size, mtime) so a symlink retarget by the daily
refresh is picked up without a restart.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import re
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

logger = logging.getLogger("synapsis.prms_snapshot")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

DEFAULT_PRMS_DB_ROOT = "/Users/smithai/workspace/coding/PRMSDB"

#: The June-2026 baseline, kept for rollback / comparison runs. Never modified.
JUNE_2026_BASELINE_PATH = f"{DEFAULT_PRMS_DB_ROOT}/fresh_13June2026/prdb_fresh.sqlite"


def prms_db_root() -> str:
    """Directory that holds ``current``, ``LATEST.json`` and the dated snapshots."""
    return os.getenv("PRMS_DB_ROOT", DEFAULT_PRMS_DB_ROOT)


def default_db_path() -> str:
    """The auto-refreshed snapshot symlink (``<root>/current``)."""
    return os.path.join(prms_db_root(), "current")


def resolve_db_path() -> str:
    """Return the PRMS SQLite path the app should read (env override first)."""
    return os.getenv("PRMS_DB_PATH", default_db_path())


def latest_json_path() -> str:
    return os.path.join(prms_db_root(), "LATEST.json")


# ---------------------------------------------------------------------------
# Snapshot metadata
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SnapshotInfo:
    """What the app knows about the PRMS snapshot it is reading.

    ``data_as_of`` is the data state (``MAX(result.last_updated_date)``, the
    freshness column). ``extracted_on`` is when the dump was taken. Both are
    ISO ``YYYY-MM-DD`` strings, or ``None`` when unknown. Always quote the
    snapshot next to any number taken from the database.
    """

    path: str
    realpath: str
    available: bool
    extracted_on: Optional[str] = None
    data_as_of: Optional[str] = None
    result_count: Optional[int] = None
    table_count: Optional[int] = None
    open_phases: tuple[str, ...] = field(default_factory=tuple)
    source: str = "unknown"  # "latest.json" | "sqlite" | "unknown"

    # -- presentation helpers -------------------------------------------------

    @property
    def label(self) -> str:
        """Short human label, e.g. ``PRMS snapshot 2026-09-07 (data as of 2026-09-04)``."""
        if not self.available:
            return "PRMS snapshot unavailable"
        if self.extracted_on and self.data_as_of and self.extracted_on != self.data_as_of:
            return f"PRMS snapshot {self.extracted_on} (data as of {self.data_as_of})"
        return f"PRMS snapshot {self.extracted_on or self.data_as_of or 'unknown date'}"

    @property
    def citation(self) -> str:
        """Footer-style source line, e.g. ``PRMS Database (snapshot 2026-09-07, data as of 2026-09-04)``."""
        if not self.available:
            return "PRMS Database (snapshot unavailable)"
        parts = []
        if self.extracted_on:
            parts.append(f"snapshot {self.extracted_on}")
        if self.data_as_of and self.data_as_of != self.extracted_on:
            parts.append(f"data as of {self.data_as_of}")
        return f"PRMS Database ({', '.join(parts) if parts else 'snapshot date unknown'})"

    @property
    def vintage_phrase(self) -> str:
        """Phrase for prose: ``the 2026-09-07 PRMS snapshot (data as of 2026-09-04)``."""
        if not self.available:
            return "the PRMS snapshot (date unavailable)"
        when = self.extracted_on or self.data_as_of or "undated"
        tail = f" (data as of {self.data_as_of})" if self.data_as_of and self.data_as_of != when else ""
        return f"the {when} PRMS snapshot{tail}"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["open_phases"] = list(self.open_phases)
        d["label"] = self.label
        d["citation"] = self.citation
        return d


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

_CACHE_TTL_SECONDS = 60.0
_cache: dict[str, tuple[float, tuple, SnapshotInfo]] = {}

_DATE8 = re.compile(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)")
_DATE_DMY = re.compile(r"(\d{1,2})([A-Za-z]{3,9})(20\d{2})")


def _iso_date(value: Any) -> Optional[str]:
    """Normalise ``2026-09-04 02:59:36.826833`` / ``20260907`` / date → ``YYYY-MM-DD``."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if re.fullmatch(r"\d{8}", s):
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
    m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
    if m:
        return m.group(1)
    return None


def _date_from_name(realpath: str) -> Optional[str]:
    """Infer the extraction date from ``fresh_20260907`` / ``prdb_20260907`` / ``fresh_13June2026``."""
    for part in reversed(realpath.split(os.sep)):
        m = _DATE8.search(part)
        if m:
            return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        m = _DATE_DMY.search(part)
        if m:
            for fmt in ("%d%B%Y", "%d%b%Y"):
                try:
                    return _dt.datetime.strptime("".join(m.groups()), fmt).date().isoformat()
                except ValueError:
                    continue
    return None


def _file_key(realpath: str) -> Optional[tuple]:
    try:
        st = os.stat(realpath)
    except OSError:
        return None
    return (realpath, st.st_size, int(st.st_mtime))


def _from_latest_json(path: str, realpath: str) -> Optional[SnapshotInfo]:
    lj = latest_json_path()
    try:
        with open(lj, "r", encoding="utf-8") as fh:
            meta = json.load(fh)
    except (OSError, ValueError):
        return None
    declared = meta.get("sqlite")
    if not declared or os.path.realpath(declared) != realpath:
        # LATEST.json describes a different file than the one we read — do not
        # borrow its date. (Happens when PRMS_DB_PATH pins the June baseline.)
        return None
    return SnapshotInfo(
        path=path,
        realpath=realpath,
        available=True,
        extracted_on=_iso_date(meta.get("snapshot_date")),
        data_as_of=_iso_date(meta.get("max_last_updated_date")),
        result_count=_int_or_none(meta.get("result_count")),
        table_count=_int_or_none(meta.get("table_count")),
        open_phases=_open_phases(realpath),
        source="latest.json",
    )


def _int_or_none(v: Any) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _open_phases(realpath: str) -> tuple[str, ...]:
    """Reporting phases still OPEN in this snapshot (``version.status = 1``).

    Numbers inside an open phase are provisional and must never be folded into
    portfolio totals without saying so. Returns labels like ``8 Reporting 2026``.
    """
    try:
        conn = sqlite3.connect(f"file:{realpath}?mode=ro", uri=True)
        try:
            rows = conn.execute(
                "SELECT id, phase_name FROM version WHERE status = 1 AND is_active = 1 ORDER BY id"
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return ()
    return tuple(f"{r[0]} {r[1]}" for r in rows)


def _from_sqlite(path: str, realpath: str) -> SnapshotInfo:
    try:
        conn = sqlite3.connect(f"file:{realpath}?mode=ro", uri=True)
        try:
            cnt, max_upd = conn.execute(
                "SELECT COUNT(*), MAX(last_updated_date) FROM result"
            ).fetchone()
            tables = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchone()[0]
        finally:
            conn.close()
    except sqlite3.Error as exc:
        logger.warning("prms_snapshot: could not read %s: %s", realpath, exc)
        return SnapshotInfo(path=path, realpath=realpath, available=False, source="unknown")

    extracted = _date_from_name(realpath)
    if extracted is None:
        try:
            extracted = _dt.date.fromtimestamp(os.stat(realpath).st_mtime).isoformat()
        except OSError:
            extracted = None
    return SnapshotInfo(
        path=path,
        realpath=realpath,
        available=True,
        extracted_on=extracted,
        data_as_of=_iso_date(max_upd),
        result_count=_int_or_none(cnt),
        table_count=_int_or_none(tables),
        open_phases=_open_phases(realpath),
        source="sqlite",
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_snapshot_info(db_path: Optional[str] = None, *, refresh: bool = False) -> SnapshotInfo:
    """Describe the snapshot behind ``db_path`` (default: :func:`resolve_db_path`).

    Never raises. When the file is missing the result has ``available=False``.
    """
    path = db_path or resolve_db_path()
    realpath = os.path.realpath(path)
    key = _file_key(realpath)
    if key is None:
        return SnapshotInfo(path=path, realpath=realpath, available=False, source="unknown")

    now = time.time()
    cached = _cache.get(realpath)
    if cached and not refresh:
        ts, cached_key, info = cached
        if cached_key == key and (now - ts) < _CACHE_TTL_SECONDS:
            return info

    info = _from_latest_json(path, realpath) or _from_sqlite(path, realpath)
    _cache[realpath] = (now, key, info)
    return info


def snapshot_label(db_path: Optional[str] = None) -> str:
    """Convenience: :attr:`SnapshotInfo.label` for the active snapshot."""
    return get_snapshot_info(db_path).label


def snapshot_citation(db_path: Optional[str] = None) -> str:
    """Convenience: :attr:`SnapshotInfo.citation` for the active snapshot."""
    return get_snapshot_info(db_path).citation


__all__ = [
    "DEFAULT_PRMS_DB_ROOT",
    "JUNE_2026_BASELINE_PATH",
    "SnapshotInfo",
    "default_db_path",
    "get_snapshot_info",
    "latest_json_path",
    "prms_db_root",
    "resolve_db_path",
    "snapshot_citation",
    "snapshot_label",
]
