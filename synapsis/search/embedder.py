"""
Thin embedding helper for the PRMS search subsystem.

Vendors the chunk-and-pool encoding + MPS env setup from
``knowledge-infrastructure/scripts/build_embeddings.py`` so the platform is
self-contained for deployment (no cross-repo import at runtime).

IMPORTANT: torch and sentence_transformers are imported LAZILY inside the
functions, never at module import. Importing this module must stay cheap and
must never fail if the heavyweight ML stack is missing — that is what lets the
`prms_search` tool degrade gracefully when the model/index is absent.
"""

from __future__ import annotations

# Set MPS memory-management env vars BEFORE torch is ever imported anywhere.
# setdefault keeps any value the host already configured. This mirrors
# build_embeddings.py:41 and bounds Metal buffer allocation to avoid OOM hangs.
import os

os.environ.setdefault("PYTORCH_MPS_HIGH_WATERMARK_RATIO", "0.9")
os.environ.setdefault("PYTORCH_MPS_LOW_WATERMARK_RATIO", "0.7")

import logging
from typing import Any

import numpy as np

logger = logging.getLogger("prms_search.embedder")

# Vendored chunk parameters (build_embeddings.py:60-62). At ~260 tokens/doc the
# PRMS corpus almost never chunks; this only guards the rare 65 KB outlier.
CHUNK_TOKENS = 2048
OVERLAP_TOKENS = 256

DEFAULT_MODEL_NAME = "Qwen/Qwen3-Embedding-0.6B"

# Module-level model cache (mirrors prefilter.py:179 / build_embeddings model load).
# Lets the server load the model once and reuse it across tool calls.
_model_cache: dict[str, Any] = {}


def load_model(model_name: str = DEFAULT_MODEL_NAME):
    """Load (and cache) a SentenceTransformer on MPS if available.

    Raises ImportError / RuntimeError if the ML stack or model is unavailable;
    callers must catch and degrade gracefully.
    """
    if model_name in _model_cache:
        return _model_cache[model_name]

    from sentence_transformers import SentenceTransformer  # lazy
    import torch  # lazy

    if hasattr(torch, "mps") and torch.backends.mps.is_available():
        logger.info("MPS (Metal) available — loading %s on GPU", model_name)
        try:
            torch.mps.empty_cache()
        except Exception:
            pass

    model = SentenceTransformer(model_name, model_kwargs={"torch_dtype": "auto"})
    _model_cache[model_name] = model
    return model


def encode_with_chunking(
    text: str,
    model,
    chunk_tokens: int = CHUNK_TOKENS,
    overlap_tokens: int = OVERLAP_TOKENS,
) -> np.ndarray:
    """Encode one text via overlapping token chunks + mean-pool + L2-normalize.

    Vendored verbatim from build_embeddings.encode_with_chunking. Short texts
    (the common PRMS case) encode directly with zero overhead.
    """
    tokenizer = model.tokenizer
    stride = chunk_tokens - overlap_tokens

    token_ids = tokenizer.encode(text, add_special_tokens=False)
    n_tokens = len(token_ids)

    if n_tokens <= chunk_tokens:
        vec = model.encode(text, normalize_embeddings=True, show_progress_bar=False)
        return np.asarray(vec, dtype=np.float32)

    chunk_texts = []
    for chunk_start in range(0, n_tokens, stride):
        chunk_end = min(chunk_start + chunk_tokens, n_tokens)
        chunk_ids = token_ids[chunk_start:chunk_end]
        chunk_texts.append(tokenizer.decode(chunk_ids, skip_special_tokens=True))
        if chunk_end >= n_tokens:
            break

    chunk_vectors = []
    for ct in chunk_texts:
        vec = model.encode(ct, normalize_embeddings=False, show_progress_bar=False)
        chunk_vectors.append(np.asarray(vec, dtype=np.float32))

    mean_vec = np.mean(np.stack(chunk_vectors, axis=0), axis=0)
    norm = np.linalg.norm(mean_vec)
    if norm > 1e-12:
        mean_vec = mean_vec / norm
    return mean_vec


def encode_query(query: str, model_name: str = DEFAULT_MODEL_NAME) -> np.ndarray:
    """Encode a user query with the asymmetric ``prompt_name="query"`` convention.

    Returns an L2-normalized 1D float32 vector of shape (dim,). Raises on
    failure; the caller (the tool) must catch and degrade gracefully.
    """
    model = load_model(model_name)
    vec = model.encode(
        query,
        prompt_name="query",
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return np.asarray(vec, dtype=np.float32)
