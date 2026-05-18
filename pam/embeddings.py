"""Embedding helper for hybrid retrieval (Phase A.1).

Lazy-loads BAAI/bge-small-en-v1.5 (384-dim) on first use. Embeddings are
returned as little-endian float32 bytes for storage in the sqlite-vec
vec_nodes virtual table.

Deterministic-fallback contract: if the model or torch is unavailable,
embed_text/embed_query return None and callers must tolerate that.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import struct
import threading
from dataclasses import dataclass
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


def embed_and_store_node(conn: sqlite3.Connection, node_id: str, text: str, *, commit: bool = True) -> bool:
    """Embed `text` and store it under `node_id` in vec_nodes + vec_node_map.

    Returns True on successful write, False if the model is unavailable,
    the text is empty, or the vec_nodes table is missing (sqlite-vec not
    loaded). The False path is the deterministic-fallback tier-down — no
    exception is raised.
    """
    vec = embed_text(text)
    if vec is None:
        return False
    try:
        cur = conn.execute("INSERT INTO vec_nodes(embedding) VALUES (?)", (vec,))
        conn.execute(
            "INSERT INTO vec_node_map(node_id, rowid) VALUES (?, ?)",
            (node_id, cur.lastrowid),
        )
        if commit:
            conn.commit()
        return True
    except sqlite3.OperationalError as exc:
        logger.debug("vec_nodes write skipped: %s", exc)
        return False


@dataclass
class BackfillStats:
    total: int = 0
    embedded: int = 0
    skipped_empty_text: int = 0
    failed: int = 0


def _embed_text_for_node(
    node_type: str,
    title: str,
    content: str,
    summary: str,
    metadata: dict,
) -> str:
    """Build the embedding text for a node row (backfill flavor).

    Entity nodes carry no content/summary, so combine title + aliases +
    category from metadata. Other types use title + summary + content;
    entity_names are not joined-in (they require an edge lookup and
    the FTS+graph layer already covers entity overlap at retrieval time).
    """
    if node_type == "entity":
        aliases = metadata.get("aliases") or []
        if not isinstance(aliases, list):
            aliases = []
        category = metadata.get("category") or ""
        parts = [title, *(str(a) for a in aliases if a), str(category) if category else ""]
        return " ".join(p for p in parts if p)
    parts = [p for p in (title, summary, content) if p]
    return " ".join(parts)


def backfill_embeddings(conn: sqlite3.Connection) -> BackfillStats:
    """Embed every node that has no vec_node_map row.

    Raises EmbeddingsUnavailable when the model isn't loadable or the
    vec_nodes table is missing — backfill is an explicit user command,
    so silent tier-down is wrong here. Idempotent: nodes already mapped
    are skipped.
    """
    has_vec_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='vec_node_map'"
    ).fetchone()
    if not has_vec_table:
        raise EmbeddingsUnavailable(
            "vec_node_map table missing — run `pam migrate` and ensure sqlite-vec is installed."
        )
    if not is_available():
        raise EmbeddingsUnavailable(
            "embedding model unavailable — install sentence-transformers and torch."
        )

    rows = conn.execute(
        """
        SELECT n.id, n.type, n.title, n.content, n.summary, n.metadata
        FROM nodes n
        LEFT JOIN vec_node_map m ON m.node_id = n.id
        WHERE m.node_id IS NULL
        """
    ).fetchall()

    stats = BackfillStats(total=len(rows))
    for row in rows:
        try:
            metadata = json.loads(row["metadata"] or "{}")
        except (TypeError, json.JSONDecodeError):
            metadata = {}
        text = _embed_text_for_node(
            node_type=row["type"],
            title=row["title"] or "",
            content=row["content"] or "",
            summary=row["summary"] or "",
            metadata=metadata,
        )
        if not text.strip():
            stats.skipped_empty_text += 1
            continue
        if embed_and_store_node(conn, row["id"], text):
            stats.embedded += 1
        else:
            stats.failed += 1
    return stats


def _reset_for_tests() -> None:
    global _model, _load_failed
    with _model_lock:
        _model = None
        _load_failed = False


__all__ = [
    "BackfillStats",
    "EMBEDDING_DIM",
    "MODEL_ID",
    "EmbeddingsUnavailable",
    "backfill_embeddings",
    "embed_and_store_node",
    "embed_query",
    "embed_text",
    "is_available",
]
