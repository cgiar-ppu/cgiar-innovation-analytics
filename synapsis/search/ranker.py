"""
Query-time ranking for PRMS hybrid search.

Implements three retrievers and a fuser over a loaded ``SearchStore``:

  * ``bm25_candidates``     — FTS5 ``bm25()`` lexical ranking, title weighted 2x
                              (echoes keyword_search's subject boost). Supports
                              filter-then-rank via a ``WHERE result_code IN (...)``
                              restriction.
  * ``semantic_candidates`` — exhaustive cosine (query_vec @ matrix.T) with a
                              ``threshold`` floor; restrictable to an eligible
                              code subset (SNAP's embeddings[subset_indices]).
  * ``rrf_fuse``            — Reciprocal Rank Fusion (k=60), the scale-free
                              fusion recommended in the design (replaces the
                              ad-hoc 1.5x both-methods bonus in prefilter.py).
  * ``similar_by_code``     — nearest neighbors of a result_code by cosine.

All ranking returns lists of ``Hit`` with provenance so the tool/agent can
explain why each result appeared.

The FTS MATCH expression is built defensively: query tokens are sanitized to
alphanumerics and OR-joined, so arbitrary user text can never form an invalid
or injectable FTS5 expression.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import numpy as np

from synapsis.search.store import SearchStore

logger = logging.getLogger("prms_search.ranker")

RRF_K = 60  # literature-standard RRF constant.


@dataclass
class Hit:
    result_code: int
    title: str
    result_type_id: int | None
    reported_year_id: int | None
    bm25_score: float | None = None
    semantic_score: float | None = None
    rrf_score: float | None = None
    matched_by: str = ""  # "keyword" | "semantic" | "both"
    corpus_source: str = ""


# ---------------------------------------------------------------------------
# FTS query sanitization
# ---------------------------------------------------------------------------

def _fts_match_expr(query: str) -> str | None:
    """Build a safe FTS5 MATCH expression from free text.

    Tokens are reduced to [a-z0-9] (lowercased), short/stopword-ish 1-char
    tokens dropped, then OR-joined so any token matching contributes. Returns
    None if no usable tokens remain (caller treats as "no lexical hits").
    """
    tokens = re.findall(r"[a-z0-9]+", query.lower())
    tokens = [t for t in tokens if len(t) > 1]
    if not tokens:
        return None
    # Quote each token to treat it as a literal term (defuses FTS operators).
    return " OR ".join(f'"{t}"' for t in tokens)


# ---------------------------------------------------------------------------
# Retrievers
# ---------------------------------------------------------------------------

def bm25_candidates(
    store: SearchStore,
    query: str,
    top_n: int,
    eligible: set[int] | None = None,
    title_weight: float = 2.0,
    desc_weight: float = 1.0,
) -> list[tuple[int, float]]:
    """Return [(result_code, bm25_score)] ranked best-first.

    FTS5 ``bm25()`` returns a value that is *more negative = more relevant*;
    we negate it so higher = better and clamp at 0. ``eligible`` restricts the
    candidate set (filter-then-rank).
    """
    match_expr = _fts_match_expr(query)
    if match_expr is None:
        return []

    conn = store.open_fts()
    try:
        sql = (
            "SELECT result_code, bm25(docs, ?, ?, ?) AS score "
            "FROM docs WHERE docs MATCH ? "
            "ORDER BY score ASC LIMIT ?"
        )
        # bm25() column weights: result_code (UNINDEXED, ignored), title, description.
        params: list = [0.0, title_weight, desc_weight, match_expr]

        if eligible is not None:
            if not eligible:
                return []
            placeholders = ",".join("?" for _ in eligible)
            sql = (
                "SELECT result_code, bm25(docs, ?, ?, ?) AS score "
                "FROM docs WHERE docs MATCH ? "
                f"AND result_code IN ({placeholders}) "
                "ORDER BY score ASC LIMIT ?"
            )
            params = [0.0, title_weight, desc_weight, match_expr, *eligible]

        params.append(top_n)
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    out: list[tuple[int, float]] = []
    for r in rows:
        # Negate so higher = more relevant; floor at 0 for readability.
        score = -float(r["score"])
        out.append((int(r["result_code"]), max(score, 0.0)))
    return out


def semantic_candidates(
    store: SearchStore,
    query_vec: np.ndarray,
    top_n: int,
    threshold: float,
    eligible: set[int] | None = None,
) -> list[tuple[int, float]]:
    """Return [(result_code, cosine)] above ``threshold``, ranked best-first.

    Vectors are pre-L2-normalized, so dot product == cosine. ``eligible``
    restricts scoring to a code subset (SNAP embeddings[subset_indices]).
    """
    q = np.asarray(query_vec, dtype=np.float32).reshape(-1)
    nq = np.linalg.norm(q)
    if nq > 1e-12:
        q = q / nq

    if eligible is not None:
        if not eligible:
            return []
        rows = [store.code_to_row[c] for c in eligible if c in store.code_to_row]
        if not rows:
            return []
        rows_arr = np.asarray(rows, dtype=np.int64)
        sub = store.vectors[rows_arr]
        sims = sub @ q
        order = np.argsort(-sims)
        out: list[tuple[int, float]] = []
        for idx in order:
            s = float(sims[idx])
            if s < threshold:
                break
            out.append((store.codes[rows_arr[idx]], s))
            if len(out) >= top_n:
                break
        return out

    sims = store.vectors @ q
    order = np.argsort(-sims)
    out = []
    for idx in order:
        s = float(sims[idx])
        if s < threshold:
            break
        out.append((store.codes[idx], s))
        if len(out) >= top_n:
            break
    return out


def similar_by_code(
    store: SearchStore,
    result_code: int,
    top_n: int,
    threshold: float,
    eligible: set[int] | None = None,
) -> list[tuple[int, float]]:
    """Nearest neighbors of ``result_code`` by cosine, excluding self."""
    row = store.code_to_row.get(result_code)
    if row is None:
        raise KeyError(result_code)
    v = store.vectors[row]
    cands = semantic_candidates(store, v, top_n + 1, threshold, eligible)
    return [(c, s) for c, s in cands if c != result_code][:top_n]


# ---------------------------------------------------------------------------
# Fusion
# ---------------------------------------------------------------------------

def rrf_fuse(
    bm25: list[tuple[int, float]],
    semantic: list[tuple[int, float]],
    top_k: int,
    bm25_weight: float = 1.0,
    semantic_weight: float = 1.0,
    k: int = RRF_K,
) -> list[tuple[int, float, str]]:
    """Reciprocal Rank Fusion of two ranked lists.

    Returns [(result_code, rrf_score, matched_by)] best-first. ``matched_by`` is
    "keyword", "semantic", or "both".
    """
    bm25_rank = {code: i for i, (code, _) in enumerate(bm25)}
    sem_rank = {code: i for i, (code, _) in enumerate(semantic)}

    all_codes = set(bm25_rank) | set(sem_rank)
    scored: list[tuple[int, float, str]] = []
    for code in all_codes:
        score = 0.0
        in_kw = code in bm25_rank
        in_sem = code in sem_rank
        if in_kw:
            score += bm25_weight * (1.0 / (k + bm25_rank[code] + 1))
        if in_sem:
            score += semantic_weight * (1.0 / (k + sem_rank[code] + 1))
        matched_by = "both" if (in_kw and in_sem) else ("keyword" if in_kw else "semantic")
        scored.append((code, score, matched_by))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]


# ---------------------------------------------------------------------------
# Hit assembly
# ---------------------------------------------------------------------------

def build_hits(
    store: SearchStore,
    fused: list[tuple[int, float, str]],
    bm25: list[tuple[int, float]],
    semantic: list[tuple[int, float]],
) -> list[Hit]:
    """Assemble Hit objects with scores + metadata + provenance."""
    bm25_map = dict(bm25)
    sem_map = dict(semantic)
    hits: list[Hit] = []
    for code, rrf, matched_by in fused:
        m = store.meta.get(code, {})
        hits.append(
            Hit(
                result_code=code,
                title=m.get("title", ""),
                result_type_id=m.get("result_type_id"),
                reported_year_id=m.get("reported_year_id"),
                bm25_score=round(bm25_map[code], 4) if code in bm25_map else None,
                semantic_score=round(sem_map[code], 4) if code in sem_map else None,
                rrf_score=round(rrf, 6),
                matched_by=matched_by,
                corpus_source=m.get("corpus_source", ""),
            )
        )
    return hits
