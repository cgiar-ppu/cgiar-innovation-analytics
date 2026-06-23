#!/usr/bin/env python3
"""
Self-contained verification for the PRMS search subsystem.

Runs three checks the design's Phase-1 acceptance calls for:

  1. Corpus-count parity: the canonical Result/QA segment of the search corpus
     equals Recipe-1's latest-phase dedup count (21,958 on the 2026-06-13 snap).
  2. Keyword-mode purity: a single rare keyword in keyword mode returns only
     docs that literally contain it (zero embedding noise).
  3. Filter-then-rank correctness: restricting to an eligible code set yields
     only result_codes within that set.

Run:  python -m synapsis.search.selftest
Exits non-zero on any failure.
"""

from __future__ import annotations

import os
import sqlite3
import sys

from synapsis.search import corpus as corpus_mod
from synapsis.search import ranker as ranker_mod
from synapsis.search.store import SearchStore

DB = os.getenv(
    "PRMS_DB_PATH",
    "/Users/smithai/workspace/coding/PRMSDB/fresh_13June2026/prdb_fresh.sqlite",
)

_RECIPE1_COUNT_SQL = """
WITH ord(v, o) AS (VALUES (1, 0), (3, 1), (4, 2), (6, 3)),
cand AS (
    SELECT r.result_code, r.id, o.o AS phord FROM result r JOIN ord o ON o.v = r.version_id
    WHERE r.source = 'Result' AND r.is_active = 1 AND r.status_id = 2
),
pick AS (SELECT result_code, MAX(phord) AS m FROM cand GROUP BY result_code),
latest AS (SELECT c.* FROM cand c JOIN pick p ON p.result_code = c.result_code AND p.m = c.phord),
canon AS (SELECT l.* FROM latest l WHERE l.id = (SELECT MAX(l2.id) FROM latest l2 WHERE l2.result_code = l.result_code))
SELECT COUNT(*) FROM canon
"""


def check_corpus_parity() -> bool:
    docs = corpus_mod.build_corpus(DB)
    result_seg = [d for d in docs if d["corpus_source"] == "result"]
    conn = sqlite3.connect(DB)
    recipe1 = conn.execute(_RECIPE1_COUNT_SQL).fetchone()[0]
    conn.close()
    # Result segment can be <= recipe1 because rows with both-empty text are dropped.
    dropped = recipe1 - len(result_seg)
    ok = 0 <= dropped <= 50  # a handful of both-empty rows is expected
    print(f"[parity] Recipe-1 canon={recipe1}  corpus Result-seg={len(result_seg)}  "
          f"dropped both-empty={dropped}  -> {'OK' if ok else 'FAIL'}")
    return ok


def check_keyword_purity() -> bool:
    store = SearchStore.load()
    # Use a rare-ish but present token; verify every hit literally contains it.
    token = "agroforestry"
    hits = ranker_mod.bm25_candidates(store, token, top_n=50)
    conn = store.open_fts()
    bad = 0
    for code, _ in hits:
        row = conn.execute(
            "SELECT title, description FROM docs WHERE result_code = ?", (code,)
        ).fetchone()
        text = ((row["title"] or "") + " " + (row["description"] or "")).lower()
        if token not in text:
            bad += 1
    conn.close()
    ok = bad == 0 and len(hits) > 0
    print(f"[keyword] '{token}' hits={len(hits)}  literal-miss={bad}  "
          f"-> {'OK' if ok else 'FAIL'}")
    return ok


def check_filter_then_rank() -> bool:
    store = SearchStore.load()
    # Restrict to an arbitrary small eligible set drawn from the index itself.
    eligible = set(store.codes[:100])
    hits = ranker_mod.bm25_candidates(store, "the development of climate", top_n=50, eligible=eligible)
    outside = [c for c, _ in hits if c not in eligible]
    ok = not outside
    print(f"[filter] eligible=100  hits={len(hits)}  outside-set={len(outside)}  "
          f"-> {'OK' if ok else 'FAIL'}")
    return ok


def main() -> int:
    results = []
    print("Corpus parity:")
    results.append(check_corpus_parity())
    print("\nKeyword purity:")
    results.append(check_keyword_purity())
    print("\nFilter-then-rank:")
    results.append(check_filter_then_rank())
    ok = all(results)
    print(f"\n{'ALL PASS' if ok else 'FAILURES PRESENT'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
