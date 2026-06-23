#!/usr/bin/env python3
"""
Build (or incrementally update) the PRMS hybrid-search index.

Produces three artifacts in ``data/search_index/`` (or $PRMS_SEARCH_INDEX_DIR):

    prms_vectors.npy          float32 (N, 1024), L2-normalized, row-aligned
    prms_vectors_codes.json   model/snapshot meta + codes + per-doc hashes
    prms_corpus.sqlite        FTS5 lexical sidecar + metadata table

Reuses the canonical Recipe-1 dedup corpus (synapsis.search.corpus) and the
vendored Qwen3-0.6B / chunk-and-pool MPS embedder (synapsis.search.embedder).

Usage:
    python -m synapsis.search.build_prms_index                # incremental
    python -m synapsis.search.build_prms_index --force        # full rebuild
    python -m synapsis.search.build_prms_index --limit 200    # quick smoke build
    python -m synapsis.search.build_prms_index --histogram    # print cosine hist

Incremental: carries forward vectors for codes whose doc_text hash is unchanged;
only re-embeds new/changed codes. A model/dim mismatch forces a full re-embed.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import numpy as np

from synapsis.search import (
    CODES_FILE,
    EMBED_MODEL_NAME,
    FTS_FILE,
    VECTORS_FILE,
)
from synapsis.search import corpus as corpus_mod
from synapsis.search import embedder as embedder_mod
from synapsis.search import store as store_mod

DEFAULT_DB = os.getenv(
    "PRMS_DB_PATH",
    "/Users/smithai/workspace/coding/PRMSDB/fresh_13June2026/prdb_fresh.sqlite",
)
DEFAULT_SNAPSHOT = "2026-06-13"


def _load_existing_hashes(codes_file: Path, expected_dim: int) -> tuple[dict[int, str], dict[int, np.ndarray]]:
    """Return ({code: hash}, {code: vector}) carried forward from a prior build.

    Empty if no prior index, model mismatch, or dim mismatch.
    """
    if not codes_file.exists() or not VECTORS_FILE.exists():
        return {}, {}
    try:
        with open(codes_file, "r", encoding="utf-8") as f:
            meta = json.load(f)
        if meta.get("model") != EMBED_MODEL_NAME or int(meta.get("dim", 0)) != expected_dim:
            print("  Prior index model/dim mismatch — full re-embed.")
            return {}, {}
        vectors = np.load(VECTORS_FILE)
        codes = [int(c) for c in meta.get("codes", [])]
        if vectors.shape[0] != len(codes):
            return {}, {}
        hashes = {int(c): h for c, h in meta.get("doc_hashes", {}).items()}
        vec_map = {codes[i]: vectors[i] for i in range(len(codes))}
        return hashes, vec_map
    except Exception as exc:
        print(f"  Could not reuse prior index ({exc}) — full re-embed.")
        return {}, {}


def build(
    db_path: str = DEFAULT_DB,
    snapshot: str = DEFAULT_SNAPSHOT,
    force: bool = False,
    limit: int | None = None,
    histogram: bool = False,
) -> dict:
    """Build the index. Returns a small stats dict."""
    t_start = time.time()

    print(f"Building PRMS search index from {db_path}")
    docs = corpus_mod.build_corpus(db_path)
    if limit:
        docs = docs[:limit]
    print(f"  Corpus: {len(docs)} canonical documents")
    by_source: dict[str, int] = {}
    for d in docs:
        by_source[d["corpus_source"]] = by_source.get(d["corpus_source"], 0) + 1
    print(f"  By source: {by_source}")
    title_only = sum(1 for d in docs if not d["has_description"])
    print(f"  Title-only docs: {title_only}")

    # Hash docs for incremental reuse.
    doc_hashes = {d["result_code"]: corpus_mod.doc_content_hash(d) for d in docs}

    # Load model (needed for embedding).
    print(f"\nLoading embedding model {EMBED_MODEL_NAME} ...")
    t0 = time.time()
    model = embedder_mod.load_model(EMBED_MODEL_NAME)
    dim = model.get_sentence_embedding_dimension()
    print(f"  Loaded in {time.time() - t0:.1f}s (dim={dim})")

    prior_hashes, prior_vecs = ({}, {}) if force else _load_existing_hashes(CODES_FILE, dim)

    # Determine which docs need embedding.
    to_embed = [
        d for d in docs
        if d["result_code"] not in prior_vecs
        or prior_hashes.get(d["result_code"]) != doc_hashes[d["result_code"]]
    ]
    reused = len(docs) - len(to_embed)
    print(f"\nEmbedding {len(to_embed)} docs ({reused} reused from prior index) ...")

    t_embed = time.time()
    vec_map: dict[int, np.ndarray] = {}
    for i, d in enumerate(to_embed):
        vec_map[d["result_code"]] = embedder_mod.encode_with_chunking(d["doc_text"], model)
        if (i + 1) % 500 == 0:
            rate = (i + 1) / (time.time() - t_embed)
            print(f"    {i + 1}/{len(to_embed)}  ({rate:.1f} docs/s)")
    embed_elapsed = time.time() - t_embed
    if to_embed:
        print(f"  Embedded {len(to_embed)} docs in {embed_elapsed:.1f}s "
              f"({len(to_embed) / max(embed_elapsed, 1e-9):.1f} docs/s)")

    # Carry forward reused vectors.
    for d in docs:
        if d["result_code"] not in vec_map:
            vec_map[d["result_code"]] = prior_vecs[d["result_code"]]

    # Assemble row-aligned matrix in corpus order.
    codes = [d["result_code"] for d in docs]
    matrix = np.stack([vec_map[c] for c in codes], axis=0).astype(np.float32)
    # Ensure L2 normalization (chunk path already normalizes; be safe).
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms < 1e-12] = 1.0
    matrix = matrix / norms

    # Persist.
    print(f"\nWriting artifacts to {VECTORS_FILE.parent} ...")
    store_mod.save_vectors(
        matrix, codes, EMBED_MODEL_NAME, snapshot, doc_hashes,
    )
    store_mod.build_fts(docs)

    vec_bytes = VECTORS_FILE.stat().st_size
    fts_bytes = FTS_FILE.stat().st_size
    total_elapsed = time.time() - t_start

    print(f"  prms_vectors.npy:   {vec_bytes / 1e6:.1f} MB")
    print(f"  prms_corpus.sqlite: {fts_bytes / 1e6:.1f} MB")
    print(f"  codes json:         {CODES_FILE.stat().st_size / 1e3:.1f} KB")
    print(f"\nDone in {total_elapsed:.1f}s — {len(docs)} docs indexed.")

    stats = {
        "docs": len(docs),
        "embedded": len(to_embed),
        "reused": reused,
        "by_source": by_source,
        "title_only": title_only,
        "dim": int(dim),
        "vec_mb": round(vec_bytes / 1e6, 1),
        "fts_mb": round(fts_bytes / 1e6, 1),
        "embed_seconds": round(embed_elapsed, 1),
        "total_seconds": round(total_elapsed, 1),
        "snapshot": snapshot,
    }

    if histogram:
        _print_self_similarity_histogram(matrix)

    return stats


def _print_self_similarity_histogram(matrix: np.ndarray, sample: int = 2000) -> None:
    """Print a rough nearest-neighbor cosine histogram to calibrate thresholds.

    Samples ``sample`` docs, finds each one's top non-self neighbor cosine, and
    bins them — the SNAP app.py:1143 calibration idea, condensed to text.
    """
    rng = np.random.default_rng(42)
    n = matrix.shape[0]
    idx = rng.choice(n, size=min(sample, n), replace=False)
    best = []
    for i in idx:
        sims = matrix @ matrix[i]
        sims[i] = -1.0
        best.append(float(sims.max()))
    best = np.array(best)
    print("\nNearest-neighbor cosine histogram (calibration):")
    for lo in np.arange(0.0, 1.0, 0.1):
        hi = lo + 0.1
        cnt = int(((best >= lo) & (best < hi)).sum())
        bar = "#" * (cnt * 50 // max(len(best), 1))
        print(f"  {lo:.1f}-{hi:.1f}: {cnt:5d} {bar}")
    print(f"  median top-1 cosine: {np.median(best):.3f}  "
          f"p25: {np.percentile(best, 25):.3f}  p75: {np.percentile(best, 75):.3f}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the PRMS hybrid search index.")
    ap.add_argument("--db", default=DEFAULT_DB, help="Path to PRMS sqlite DB.")
    ap.add_argument("--snapshot", default=DEFAULT_SNAPSHOT, help="Snapshot date tag.")
    ap.add_argument("--force", action="store_true", help="Full rebuild (no reuse).")
    ap.add_argument("--limit", type=int, default=None, help="Cap docs (smoke test).")
    ap.add_argument("--histogram", action="store_true", help="Print cosine histogram.")
    args = ap.parse_args()
    build(
        db_path=args.db,
        snapshot=args.snapshot,
        force=args.force,
        limit=args.limit,
        histogram=args.histogram,
    )


if __name__ == "__main__":
    main()
