"""
Canonical PRMS search corpus construction.

Builds one document per canonical `result_code` using the SAME latest-phase
dedup CTE the platform uses for headline counts (references/prms_query_cookbook.md
Recipe 1 / prms_cheatsheet.md), so any result_code surfaced by `prms_search`
is consistent with the agent's `DISTINCT result_code` counting rules.

Two corpus segments are unioned:

  * ``Result`` / QA'd canonical rows  (source='Result', is_active=1, status_id=2)
      → latest-phase dedup, one representative row per result_code.
  * ``bilateral`` rows                (source='API',    is_active=1, status_id=6)
      → latest id per result_code. These have no version_id phase ordering, so
        we simply take the MAX(id) per code among the eligible rows.

Each emitted document is a dict:
    {
        "result_code":     int,
        "title":           str,
        "description":     str,
        "doc_text":        str,   # title + "\n\n" + description
        "has_description": bool,
        "result_type_id":  int | None,
        "reported_year_id":int | None,
        "corpus_source":   "result" | "bilateral",
    }

Rows where BOTH title and description are empty/whitespace are dropped (nothing
to search). Title-only rows are kept (a title alone is a valid topical signal).
"""

from __future__ import annotations

import hashlib
import sqlite3
from typing import Any

# Latest-phase dedup over Result/QA rows (Recipe 1). Selects the representative
# title+description per result_code.
_CANON_RESULT_SQL = """
WITH ord(v, o) AS (VALUES (1, 0), (3, 1), (4, 2), (6, 3)),
cand AS (
    SELECT r.result_code, r.id, r.result_type_id, r.reported_year_id,
           r.title, r.description, o.o AS phord
    FROM result r JOIN ord o ON o.v = r.version_id
    WHERE r.source = 'Result' AND r.is_active = 1 AND r.status_id = 2
),
pick AS (SELECT result_code, MAX(phord) AS m FROM cand GROUP BY result_code),
latest AS (
    SELECT c.* FROM cand c
    JOIN pick p ON p.result_code = c.result_code AND p.m = c.phord
),
canon AS (
    SELECT l.* FROM latest l
    WHERE l.id = (SELECT MAX(l2.id) FROM latest l2 WHERE l2.result_code = l.result_code)
)
SELECT result_code, id, result_type_id, reported_year_id, title, description
FROM canon
"""

# Bilateral (W3) rows: latest id per code among the eligible API/status-6 rows.
_CANON_BILATERAL_SQL = """
WITH cand AS (
    SELECT r.result_code, r.id, r.result_type_id, r.reported_year_id,
           r.title, r.description
    FROM result r
    WHERE r.source = 'API' AND r.is_active = 1 AND r.status_id = 6
),
canon AS (
    SELECT c.* FROM cand c
    WHERE c.id = (SELECT MAX(c2.id) FROM cand c2 WHERE c2.result_code = c.result_code)
)
SELECT result_code, id, result_type_id, reported_year_id, title, description
FROM canon
"""


def _clean(value: Any) -> str:
    """Coerce a possibly-NULL DB value to a stripped string."""
    if value is None:
        return ""
    return str(value).strip()


def _make_doc(row: sqlite3.Row, corpus_source: str) -> dict | None:
    """Turn a DB row into a corpus document dict, or None if it has no text."""
    title = _clean(row["title"])
    description = _clean(row["description"])

    # Drop rows with no searchable text at all.
    if not title and not description:
        return None

    if title and description:
        doc_text = f"{title}\n\n{description}"
    else:
        # Title-only or description-only: the non-empty field is the doc_text.
        doc_text = title or description

    return {
        "result_code": int(row["result_code"]),
        "title": title,
        "description": description,
        "doc_text": doc_text,
        "has_description": bool(description),
        "result_type_id": row["result_type_id"],
        "reported_year_id": row["reported_year_id"],
        "corpus_source": corpus_source,
    }


def build_corpus(db_path: str) -> list[dict]:
    """Build the full canonical search corpus from the PRMS database.

    Returns a list of document dicts (see module docstring), ordered Result
    segment first then bilateral. Duplicate result_codes across segments are
    deduplicated (Result wins) — though in practice the two segments are
    disjoint by construction (verified: zero overlap on the 2026-06-13 snapshot).
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        docs: list[dict] = []
        seen: set[int] = set()

        for sql, source in (
            (_CANON_RESULT_SQL, "result"),
            (_CANON_BILATERAL_SQL, "bilateral"),
        ):
            for row in conn.execute(sql):
                code = int(row["result_code"])
                if code in seen:
                    continue
                doc = _make_doc(row, source)
                if doc is None:
                    continue
                docs.append(doc)
                seen.add(code)

        return docs
    finally:
        conn.close()


def doc_content_hash(doc: dict) -> str:
    """Stable content hash of a document's searchable text.

    Used for incremental rebuilds: only re-embed codes whose canonical
    ``doc_text`` changed between snapshots.
    """
    h = hashlib.sha256()
    h.update(doc["doc_text"].encode("utf-8", errors="replace"))
    return h.hexdigest()
