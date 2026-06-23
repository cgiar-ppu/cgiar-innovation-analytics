"""
PRMS hybrid search MCP tool — theme/topic discovery over result title+description.

Returns ranked canonical ``result_code``s with BM25 + semantic scores and
provenance, supporting three modes (keyword / hybrid / semantic), a
"find similar to a given result_code" mode, structured filter-then-rank, and a
semantic "close enough" threshold so single-keyword searches stay clean.

Design: /Users/smithai/workspace/analysis/cgiar-ia/04-hybrid-search-design.md

Runtime realism:
  * The Qwen embedding model + the index are LAZY-LOADED on the first search
    that needs them (never at import or server startup) so boot time is
    unaffected.
  * If the index or model is missing, the tool DEGRADES GRACEFULLY: it returns a
    clear "search index not available" message and never raises an import-time
    error that could break the app. ``mode="keyword"`` still works with only the
    FTS sidecar present (no model needed).
  * Query embedding + cosine + FTS all run inside a worker thread (mirroring
    prms_query's threaded SQL execution) so the async server event loop is not
    blocked.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path
from typing import Any

from claude_agent_sdk import tool

from synapsis.utils.responses import error_response, success_response

# NOTE: synapsis.search and its submodules are import-safe (no torch/ST at
# import time), so importing them here cannot break the app even with no index.
from synapsis.search import EMBED_MODEL_NAME, FTS_FILE
from synapsis.search import ranker as ranker_mod
from synapsis.search.store import IndexNotAvailable, SearchStore

# Reuse prms_query's validated read-only SQL path for filter-then-rank.
from synapsis.tools.prms_query import (
    PRMS_DB_PATH,
    _execute_with_timeout,
    _validate_sql,
    _TimeoutError,
)

# ---------------------------------------------------------------------------
# Defaults (design §4.1–§5.1)
# ---------------------------------------------------------------------------

DEFAULT_TOP_K = 25
DEFAULT_SEMANTIC_THRESHOLD = 0.35   # "close enough" floor for search
DEFAULT_SIMILAR_THRESHOLD = 0.58    # stricter floor for "similar to this result"
VALID_MODES = {"keyword", "hybrid", "semantic"}

# Per-retriever candidate depth before fusion / final top_k slice.
_CANDIDATE_DEPTH = 200

# ---------------------------------------------------------------------------
# Lazy-loaded store cache
# ---------------------------------------------------------------------------

_store_lock = threading.Lock()
_store_cache: dict[str, SearchStore] = {}


def _get_store() -> SearchStore:
    """Lazily load and cache the SearchStore. Raises IndexNotAvailable if absent."""
    with _store_lock:
        if "store" not in _store_cache:
            _store_cache["store"] = SearchStore.load()
        return _store_cache["store"]


def index_present() -> bool:
    """Cheap check: does the FTS sidecar exist? (lexical mode needs only this)."""
    return Path(FTS_FILE).exists()


# ---------------------------------------------------------------------------
# Structured filter compilation -> eligible result_code set
# ---------------------------------------------------------------------------

def _compile_filters_sql(filters: dict) -> str | None:
    """Compile a structured ``filters`` dict into a SELECT returning result_code.

    Supported keys (all optional, AND-combined):
        year / years:        int or list[int]   -> reported_year_id
        result_type_id:      int or list[int]
        country_iso3:        list[str]           -> via result_countries/clarisa
        irl_min:             int                 -> investment/readiness level
    The compiled query runs through the same validated read-only path as
    prms_query. Geography/IRL joins are intentionally conservative; callers
    who need richer geography (country-OR-region UNION) should pass an explicit
    ``filter_sql`` instead.

    Returns None if no usable filter keys are present.
    """
    clauses: list[str] = ["r.source IN ('Result','API')", "r.is_active = 1"]

    def _as_list(v):
        if v is None:
            return None
        return v if isinstance(v, (list, tuple)) else [v]

    years = _as_list(filters.get("year") or filters.get("years"))
    if years:
        vals = ",".join(str(int(y)) for y in years)
        clauses.append(f"r.reported_year_id IN ({vals})")

    types = _as_list(filters.get("result_type_id"))
    if types:
        vals = ",".join(str(int(t)) for t in types)
        clauses.append(f"r.result_type_id IN ({vals})")

    # Only emit a query if the caller actually constrained something beyond the
    # always-on source/is_active guard.
    constrained = bool(years or types)
    if not constrained:
        return None

    return (
        "SELECT DISTINCT r.result_code FROM result r WHERE "
        + " AND ".join(clauses)
    )


def _resolve_eligible(filter_sql: str | None, filters: dict | None) -> tuple[set[int] | None, str | None]:
    """Run the filter SQL (explicit or compiled) and return the eligible code set.

    Returns (eligible_set_or_None, error_message_or_None). ``None`` eligible set
    means "no filter — search the whole corpus".
    """
    sql = None
    if filter_sql and filter_sql.strip():
        sql = filter_sql.strip()
    elif filters:
        sql = _compile_filters_sql(filters)

    if not sql:
        return None, None

    err = _validate_sql(sql)
    if err:
        return None, f"filter_sql validation error: {err}"

    if not Path(PRMS_DB_PATH).is_file():
        return None, f"PRMS database not found at {PRMS_DB_PATH}."

    try:
        rows, columns, _ = _execute_with_timeout(PRMS_DB_PATH, sql)
    except _TimeoutError as exc:
        return None, str(exc)
    except sqlite3.Error as exc:
        return None, f"filter SQL error: {exc}"

    if not columns or "result_code" not in columns:
        return None, "filter_sql must SELECT a 'result_code' column."

    eligible = {int(r["result_code"]) for r in rows if r.get("result_code") is not None}
    return eligible, None


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def _format_hits(
    hits: list,
    *,
    header: str,
    mode: str,
    eligible_size: int | None,
    store: SearchStore,
    extra_meta: list[str] | None = None,
) -> str:
    lines: list[str] = [header, ""]
    if not hits:
        lines.append("No matching results above the configured thresholds.")
    else:
        cols = ["result_code", "title", "type", "year", "bm25", "semantic", "rrf", "matched_by", "src"]
        lines.append(" | ".join(cols))
        lines.append(" | ".join("---" for _ in cols))
        for h in hits:
            title = (h.title or "")[:70]
            lines.append(" | ".join([
                str(h.result_code),
                title,
                str(h.result_type_id) if h.result_type_id is not None else "",
                str(h.reported_year_id) if h.reported_year_id is not None else "",
                f"{h.bm25_score:.3f}" if h.bm25_score is not None else "-",
                f"{h.semantic_score:.3f}" if h.semantic_score is not None else "-",
                f"{h.rrf_score:.5f}" if h.rrf_score is not None else "-",
                h.matched_by,
                h.corpus_source,
            ]))

    meta = ["", "---", f"Mode: {mode}"]
    if eligible_size is not None:
        meta.append(f"Eligible set size (filter-then-rank): {eligible_size}")
    meta.append(f"Index: {len(store.codes)} docs | model {store.model} | snapshot {store.snapshot}")
    if extra_meta:
        meta.extend(extra_meta)
    meta.append("Next: use prms_query on these result_codes for full structured detail.")
    return "\n".join(lines + meta)


# ---------------------------------------------------------------------------
# Core search (runs in a worker thread)
# ---------------------------------------------------------------------------

def _run_search(args: dict[str, Any]) -> dict[str, Any]:
    query = (args.get("query") or "").strip()
    mode = (args.get("mode") or "hybrid").strip().lower()
    top_k = int(args.get("top_k") or DEFAULT_TOP_K)
    semantic_threshold = float(args.get("semantic_threshold") or DEFAULT_SEMANTIC_THRESHOLD)
    similar_to = args.get("similar_to_result_code")
    similar_threshold = float(args.get("similar_threshold") or DEFAULT_SIMILAR_THRESHOLD)
    filter_sql = args.get("filter_sql")
    filters = args.get("filters")
    bm25_weight = float(args.get("bm25_weight") or 1.0)
    semantic_weight = float(args.get("semantic_weight") or 1.0)

    if top_k < 1:
        return error_response("top_k must be a positive integer.")
    if mode not in VALID_MODES:
        return error_response(
            f"Invalid mode '{mode}'. Use one of: keyword, hybrid, semantic."
        )

    # Graceful degradation: no index at all.
    if not index_present():
        return error_response(
            "Search index not available — the PRMS search index has not been "
            "built yet. Run `python -m synapsis.search.build_prms_index` to "
            "build it. (Falling back to prms_query with SQL LIKE is an option "
            "for exact keyword matching in the meantime.)"
        )

    try:
        store = _get_store()
    except IndexNotAvailable as exc:
        return error_response(f"Search index not available: {exc}")

    # Resolve structured filters -> eligible set (filter-then-rank).
    eligible, ferr = _resolve_eligible(filter_sql, filters)
    if ferr:
        return error_response(ferr)
    eligible_size = len(eligible) if eligible is not None else None
    if eligible is not None and not eligible:
        return success_response(
            "Filter matched zero result_codes; nothing to search.\n---\n"
            f"Mode: {mode} | filter returned an empty eligible set."
        )

    # -------- similar_to_result_code mode --------
    if similar_to is not None:
        try:
            code = int(similar_to)
        except (TypeError, ValueError):
            return error_response("similar_to_result_code must be an integer.")
        if code not in store.code_to_row:
            return error_response(
                f"result_code {code} is not in the search index (it may be "
                "non-canonical or have no searchable text)."
            )
        neighbors = ranker_mod.similar_by_code(
            store, code, top_k, similar_threshold, eligible
        )
        sem_list = neighbors
        fused = [(c, s, "semantic") for c, s in neighbors]
        hits = ranker_mod.build_hits(store, fused, [], sem_list)
        return success_response(_format_hits(
            hits,
            header=(
                f"Results similar to result_code {code} "
                f"(cosine >= {similar_threshold}): {len(hits)} found."
            ),
            mode="similar",
            eligible_size=eligible_size,
            store=store,
            extra_meta=[f"Similar threshold: {similar_threshold}"],
        ))

    # -------- text query modes --------
    if not query:
        return error_response(
            "Provide a 'query' (free-text theme/keyword) or a "
            "'similar_to_result_code'."
        )

    bm25: list = []
    semantic: list = []

    if mode in ("keyword", "hybrid"):
        bm25 = ranker_mod.bm25_candidates(store, query, _CANDIDATE_DEPTH, eligible)

    if mode in ("semantic", "hybrid"):
        # Lazy model load happens here; degrade gracefully if it fails.
        try:
            from synapsis.search import embedder as embedder_mod
            qvec = embedder_mod.encode_query(query, EMBED_MODEL_NAME)
        except Exception as exc:  # model/ML stack missing or load failure
            if mode == "semantic":
                return error_response(
                    "Semantic search unavailable — the embedding model could "
                    f"not be loaded ({exc}). Try mode='keyword' for lexical "
                    "search, which needs no model."
                )
            # hybrid: fall back to keyword-only with a note.
            semantic = []
            qvec = None
        else:
            semantic = ranker_mod.semantic_candidates(
                store, qvec, _CANDIDATE_DEPTH, semantic_threshold, eligible
            )

    # Fuse / slice.
    if mode == "keyword":
        fused = [(c, 1.0 / (i + 1), "keyword") for i, (c, _) in enumerate(bm25[:top_k])]
    elif mode == "semantic":
        fused = [(c, s, "semantic") for c, s in semantic[:top_k]]
    else:  # hybrid
        fused = ranker_mod.rrf_fuse(
            bm25, semantic, top_k,
            bm25_weight=bm25_weight, semantic_weight=semantic_weight,
        )

    hits = ranker_mod.build_hits(store, fused, bm25, semantic)

    note = []
    if mode == "hybrid" and not semantic and bm25:
        note.append("Note: semantic retriever returned no candidates (or model "
                    "unavailable); results are keyword-only.")

    return success_response(_format_hits(
        hits,
        header=f"Search '{query}' [{mode}]: {len(hits)} results (top_k={top_k}).",
        mode=mode,
        eligible_size=eligible_size,
        store=store,
        extra_meta=([f"Semantic threshold: {semantic_threshold}"] + note),
    ))


# ---------------------------------------------------------------------------
# MCP Tool
# ---------------------------------------------------------------------------

@tool(
    "prms_search",
    "Theme/topic search over PRMS result title+description. Returns ranked "
    "canonical result_codes with BM25 + semantic scores and provenance. Combine "
    "with structured filters (search runs WITHIN the filtered set so counts stay "
    "consistent with canonical dedup rules); supports 'find results similar to a "
    "given result_code'. Modes: 'keyword' (exact lexical, zero embedding noise), "
    "'hybrid' (BM25 + semantic fused via RRF, default), 'semantic' (conceptual). "
    "ASK THE USER whether they want exact-keyword-only or also semantically "
    "related themes before running, to avoid noise. Returns result_codes you can "
    "then pass to prms_query for full structured detail.",
    {
        "query": str,
        "mode": str,
        "top_k": int,
        "semantic_threshold": float,
        "filter_sql": str,
        "filters": dict,
        "similar_to_result_code": int,
        "similar_threshold": float,
        "bm25_weight": float,
        "semantic_weight": float,
    },
)
async def prms_search(args: dict[str, Any]) -> dict[str, Any]:
    """Run a PRMS hybrid search.

    All heavy work (FTS, query embedding, cosine) runs in a worker thread so the
    async event loop is not blocked, mirroring prms_query's threaded execution.
    """
    result_holder: dict[str, Any] = {}

    def _worker():
        try:
            result_holder["result"] = _run_search(args)
        except Exception as exc:  # never let the tool raise
            result_holder["result"] = error_response(
                f"Unexpected error during search: {exc}"
            )

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    # Generous ceiling: model cold-load (~7s) + embed + cosine + FTS.
    t.join(timeout=120)
    if t.is_alive():
        return error_response(
            "Search timed out after 120s (possible model cold-load stall). "
            "Try mode='keyword' which needs no embedding model."
        )
    return result_holder.get("result", error_response("Search produced no result."))
