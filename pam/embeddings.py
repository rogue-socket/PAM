"""Embedding helper for hybrid retrieval (Phase A.1).

Lazy-loads BAAI/bge-small-en-v1.5 (384-dim) on first use. Embeddings are
returned as little-endian float32 bytes for storage in the sqlite-vec
vec_nodes virtual table.

Deterministic-fallback contract: if the model or torch is unavailable,
embed_text/embed_query return None and callers must tolerate that.
"""
from __future__ import annotations

import logging
import os
import struct
import threading
from typing import Sequence

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 384
MODEL_ID = "BAAI/bge-small-en-v1.5"
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

_model_lock = threading.Lock()
_model = None
_load_failed = False


class EmbeddingsUnavailable(RuntimeError):
    pass


def _disabled_by_env() -> bool:
    return os.getenv("PAM_DISABLE_EMBEDDINGS", "").lower() in {"1", "true", "yes"}


def _get_model():
    global _model, _load_failed
    if _disabled_by_env():
        return None
    if _load_failed:
        return None
    if _model is not None:
        return _model
    with _model_lock:
        if _model is not None:
            return _model
        if _load_failed:
            return None
        try:
            from sentence_transformers import SentenceTransformer
            _model = SentenceTransformer(MODEL_ID)
        except Exception as exc:
            _load_failed = True
            logger.warning("Embedding model unavailable (%s); embeddings disabled", exc)
            return None
    return _model


def _vector_to_bytes(vec) -> bytes:
    return struct.pack(f"<{EMBEDDING_DIM}f", *vec)


def embed_text(text: str) -> bytes | None:
    """Embed a document/passage. Returns None if model is unavailable."""
    if not text or not text.strip():
        return None
    model = _get_model()
    if model is None:
        return None
    try:
        vec = model.encode(text, normalize_embeddings=True)
    except Exception as exc:
        logger.warning("embed_text failed: %s", exc)
        return None
    return _vector_to_bytes(vec.tolist())


def embed_query(text: str) -> bytes | None:
    """Embed a query. Applies BGE's recommended retrieval prefix."""
    if not text or not text.strip():
        return None
    model = _get_model()
    if model is None:
        return None
    try:
        vec = model.encode(QUERY_PREFIX + text, normalize_embeddings=True)
    except Exception as exc:
        logger.warning("embed_query failed: %s", exc)
        return None
    return _vector_to_bytes(vec.tolist())


def is_available() -> bool:
    return _get_model() is not None


def _reset_for_tests() -> None:
    global _model, _load_failed
    with _model_lock:
        _model = None
        _load_failed = False


__all__ = [
    "EMBEDDING_DIM",
    "MODEL_ID",
    "EmbeddingsUnavailable",
    "embed_query",
    "embed_text",
    "is_available",
]
