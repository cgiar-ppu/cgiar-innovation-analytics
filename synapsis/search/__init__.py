"""
PRMS hybrid search subsystem.

Provides offline index construction (`build_prms_index`) and a query-time
ranking engine (`store`, `ranker`) used by the `prms_search` MCP tool.

The subsystem is import-safe even when no index has been built and when the
embedding model is unavailable: importing this package must never fail or pull
in heavyweight dependencies (torch / sentence-transformers) at import time.
Those are lazy-loaded only when a semantic search actually runs.
"""

# Default on-disk locations for the generated index artifacts. Kept here so the
# builder and the query-time store agree on a single source of truth.
import os
from pathlib import Path

# Repo root = three levels up from this file (synapsis/search/__init__.py).
_REPO_ROOT = Path(__file__).resolve().parents[2]

# Allow override via env so the container can point at a baked-in / S3-synced
# index location without code changes.
SEARCH_INDEX_DIR = Path(
    os.getenv("PRMS_SEARCH_INDEX_DIR", str(_REPO_ROOT / "data" / "search_index"))
)

VECTORS_FILE = SEARCH_INDEX_DIR / "prms_vectors.npy"
CODES_FILE = SEARCH_INDEX_DIR / "prms_vectors_codes.json"
FTS_FILE = SEARCH_INDEX_DIR / "prms_corpus.sqlite"

# Embedding model — matches knowledge-infrastructure/build_embeddings.py so the
# already-cached model and asymmetric query prompt convention are reused.
EMBED_MODEL_NAME = "Qwen/Qwen3-Embedding-0.6B"
EMBED_DIM = 1024

__all__ = [
    "SEARCH_INDEX_DIR",
    "VECTORS_FILE",
    "CODES_FILE",
    "FTS_FILE",
    "EMBED_MODEL_NAME",
    "EMBED_DIM",
]
