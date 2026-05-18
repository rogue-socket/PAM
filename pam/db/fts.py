from __future__ import annotations

import re
import sqlite3

from pam.db.nodes import Node, row_to_node
from pam.db.transaction import transaction


MATCH_TERM_PATTERN = re.compile(r"\w+")
MATCH_OPERATORS = {"AND", "OR", "NOT"}


def _build_safe_match_query(raw_query: str) -> str:
    terms: list[str] = []
    seen: set[str] = set()

    for chunk in raw_query.split():
        if chunk.upper() in MATCH_OPERATORS:
            continue
        for term in MATCH_TERM_PATTERN.findall(chunk):
            normalized = term.strip()
            if not normalized:
                continue
            lowered = normalized.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            terms.append(f'"{normalized}"')

    return " OR ".join(terms)


def _normalized_limit(limit: int) -> int:
    return max(1, limit)


def _safe_match_query(raw_query: str) -> str:
    return _build_safe_match_query(raw_query.strip())


def _execute_fts_query(
    conn: sqlite3.Connection,
    query: str,
    params: dict[str, object],
) -> list[sqlite3.Row]:
    return conn.execute(query, params).fetchall()


def fts_search(
    conn: sqlite3.Connection,
    query_string: str,
    status: str = "active",
    workspace_id: str | None = None,
    time_start: str | None = None,
    time_end: str | None = None,
    limit: int = 50,
) -> list[tuple[Node, float]]:
    """
    Full-text search. Returns list of (node, fts_rank) tuples.
    Time filters use valid_at.
    Query string uses FTS5 syntax: "keyword1 OR keyword2 OR keyword3".
    """
    query_string = _safe_match_query(query_string)
    if not query_string:
        return []

    rows = _execute_fts_query(
        conn,
        """
        SELECT n.*, bm25(fts_index) AS fts_rank
        FROM fts_index
        JOIN nodes n ON n.id = fts_index.node_id
        WHERE fts_index MATCH :query_string
          AND n.status = :status
          AND (:workspace_id IS NULL OR n.workspace_id = :workspace_id)
          AND (:start IS NULL OR n.valid_at >= :start)
          AND (:end IS NULL OR n.valid_at <= :end)
        ORDER BY fts_rank
        LIMIT :limit
        """,
        {
            "query_string": query_string,
            "status": status,
            "workspace_id": workspace_id,
            "start": time_start,
            "end": time_end,
            "limit": _normalized_limit(limit),
        },
    )
    return [(row_to_node(row), row["fts_rank"]) for row in rows]


def fts_search_entities(
    conn: sqlite3.Connection,
    entity_name: str,
    limit: int = 20,
    workspace_id: str | None = None,
) -> list[Node]:
    """
    Search FTS for entity nodes matching a name.
    Used by entity_linker.py for pre-filtering before fuzzy match.
    """
    entity_name = _safe_match_query(entity_name)
    if not entity_name:
        return []

    rows = _execute_fts_query(
        conn,
        """
        SELECT n.*
        FROM fts_index
        JOIN nodes n ON n.id = fts_index.node_id
        WHERE fts_index MATCH :entity_name
          AND n.type = 'entity'
          AND (:workspace_id IS NULL OR n.workspace_id = :workspace_id)
        ORDER BY bm25(fts_index)
        LIMIT :limit
        """,
        {
            "entity_name": entity_name,
            "limit": _normalized_limit(limit),
            "workspace_id": workspace_id,
        },
    )
    return [row_to_node(row) for row in rows]


def rebuild_fts(conn: sqlite3.Connection) -> int:
    """Wipe and rebuild fts_index from nodes. Returns count indexed."""
    with transaction(conn):
        conn.execute("DELETE FROM fts_index")
        conn.execute(
            """
            INSERT INTO fts_index(node_id, title, content, summary)
            SELECT id, title, content, summary FROM nodes
            """
        )
        return conn.execute("SELECT COUNT(*) FROM fts_index").fetchone()[0]


__all__ = ["fts_search", "fts_search_entities"]