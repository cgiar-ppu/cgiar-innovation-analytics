"""
PRMS search index store: load/save the vector matrix + codes metadata + the
FTS5 lexical sidecar.

Two artifacts back the index:

  * ``prms_vectors.npy``        — float32 (N, dim), L2-normalized, row-aligned to
                                  the ``codes`` list (SNAP-style, supports
                                  integer-index subsetting for filter-then-rank).
  * ``prms_vectors_codes.json`` — {"model", "snapshot", "dim", "codes": [...],
                                  "doc_hashes": {code: hash}, ...} plus a
                                  reverse code->row map built on load.
  * ``prms_corpus.sqlite``      — FTS5 virtual table ``docs`` (built-in bm25())
                                  + co-located metadata table ``meta`` for
                                  in-SQL structured filtering (filter-then-rank).

The store is read-only at query time. It is designed to load lazily and to be
absent without breaking imports: ``SearchStore.load`` raises ``IndexNotAvailable``
which the tool catches to return a clean "index not available" message.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from synapsis.search import CODES_FILE, FTS_FILE, VECTORS_FILE

logger = logging.getLogger("prms_search.store")


class IndexNotAvailable(RuntimeError):
    """Raised when a required index artifact is missing or unreadable."""


# ---------------------------------------------------------------------------
# Build-time writers
# ---------------------------------------------------------------------------

def save_vectors(
    vectors: np.ndarray,
    codes: list[int],
    model: str,
    snapshot: str,
    doc_hashes: dict[int, str],
    vectors_file: Path = VECTORS_FILE,
    codes_file: Path = CODES_FILE,
) -> None:
    """Persist the vector matrix and its codes/metadata sidecar."""
    vectors_file.parent.mkdir(parents=True, exist_ok=True)
    np.save(vectors_file, vectors.astype(np.float32))
    meta = {
        "model": model,
        "snapshot": snapshot,
        "dim": int(vectors.shape[1]) if vectors.ndim == 2 else 0,
        "count": len(codes),
        "codes": [int(c) for c in codes],
        "doc_hashes": {str(c): h for c, h in doc_hashes.items()},
    }
    with open(codes_file, "w", encoding="utf-8") as f:
        json.dump(meta, f)


def build_fts(
    docs: list[dict],
    fts_file: Path = FTS_FILE,
) -> None:
    """(Re)build the FTS5 lexical sidecar + metadata table from documents.

    ``docs`` are the dicts emitted by ``corpus.build_corpus``. The title and
    description live in separate FTS columns so bm25() can weight the title.
    """
    fts_file.parent.mkdir(parents=True, exist_ok=True)
    # Full rebuild: drop any prior file.
    if fts_file.exists():
        fts_file.unlink()

    conn = sqlite3.connect(str(fts_file))
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE docs USING fts5("
            "result_code UNINDEXED, title, description, "
            "tokenize='porter unicode61')"
        )
        conn.execute(
            "CREATE TABLE meta ("
            "result_code INTEGER PRIMARY KEY, "
            "result_type_id INTEGER, "
            "reported_year_id INTEGER, "
            "has_description INTEGER, "
            "corpus_source TEXT, "
            "title TEXT)"
        )
        conn.executemany(
            "INSERT INTO docs (result_code, title, description) VALUES (?, ?, ?)",
            [(d["result_code"], d["title"], d["description"]) for d in docs],
        )
        conn.executemany(
            "INSERT INTO meta (result_code, result_type_id, reported_year_id, "
            "has_description, corpus_source, title) VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    d["result_code"],
                    d["result_type_id"],
                    d["reported_year_id"],
                    1 if d["has_description"] else 0,
                    d["corpus_source"],
                    d["title"],
                )
                for d in docs
            ],
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Query-time loader
# ---------------------------------------------------------------------------

@dataclass
class SearchStore:
    """In-memory handle to the loaded index (vectors + metadata + FTS path)."""

    vectors: np.ndarray
    codes: list[int]
    code_to_row: dict[int, int]
    model: str
    snapshot: str
    dim: int
    fts_path: str
    # result_code -> small metadata dict, populated from the FTS meta table.
    meta: dict[int, dict] = field(default_factory=dict)

    @classmethod
    def load(
        cls,
        vectors_file: Path = VECTORS_FILE,
        codes_file: Path = CODES_FILE,
        fts_file: Path = FTS_FILE,
    ) -> "SearchStore":
        """Load all index artifacts. Raises IndexNotAvailable if any is missing."""
        missing = [
            str(p) for p in (vectors_file, codes_file, fts_file) if not Path(p).exists()
        ]
        if missing:
            raise IndexNotAvailable(
                "Search index artifact(s) not found: " + ", ".join(missing)
            )

        try:
            vectors = np.load(vectors_file)
            with open(codes_file, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except Exception as exc:  # corrupt / partial index
            raise IndexNotAvailable(f"Failed to load index: {exc}") from exc

        codes = [int(c) for c in meta.get("codes", [])]
        if vectors.ndim != 2 or vectors.shape[0] != len(codes):
            raise IndexNotAvailable(
                f"Index shape mismatch: vectors={getattr(vectors, 'shape', None)} "
                f"vs {len(codes)} codes"
            )

        code_to_row = {c: i for i, c in enumerate(codes)}

        store = cls(
            vectors=vectors.astype(np.float32, copy=False),
            codes=codes,
            code_to_row=code_to_row,
            model=meta.get("model", ""),
            snapshot=meta.get("snapshot", ""),
            dim=int(meta.get("dim", vectors.shape[1])),
            fts_path=str(fts_file),
        )
        store._load_meta()
        return store

    def _load_meta(self) -> None:
        """Populate per-code metadata from the FTS sidecar's meta table."""
        conn = sqlite3.connect(self.fts_path)
        try:
            conn.row_factory = sqlite3.Row
            for row in conn.execute(
                "SELECT result_code, result_type_id, reported_year_id, "
                "has_description, corpus_source, title FROM meta"
            ):
                self.meta[int(row["result_code"])] = {
                    "result_type_id": row["result_type_id"],
                    "reported_year_id": row["reported_year_id"],
                    "has_description": bool(row["has_description"]),
                    "corpus_source": row["corpus_source"],
                    "title": row["title"] or "",
                }
        finally:
            conn.close()

    def open_fts(self) -> sqlite3.Connection:
        """Open a read-only connection to the FTS sidecar."""
        conn = sqlite3.connect(self.fts_path)
        conn.execute("PRAGMA query_only = ON;")
        conn.row_factory = sqlite3.Row
        return conn
