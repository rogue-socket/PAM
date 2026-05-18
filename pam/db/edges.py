from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pam.db.schema import datetime_to_iso, iso_to_datetime, utcnow


@dataclass
class Edge:
    source_id: str
    target_id: str
    relation: Literal["REFERS_TO", "DERIVED_FROM", "RELATED", "CONTRADICTS", "SUPERSEDES"]
    weight: float
    fact: str
    created_at: datetime


def _clamp_weight(value: float) -> float:
    return max(0.0, min(1.0, value))


def row_to_edge(row: sqlite3.Row) -> Edge:
    return Edge(
        source_id=row["source_id"],
        target_id=row["target_id"],
        relation=row["relation"],
        weight=row["weight"],
        fact=row["fact"],
        created_at=iso_to_datetime(row["created_at"]),
    )


def create_edge(conn: sqlite3.Connection, edge: Edge, *, commit: bool = True) -> bool:
    """Insert an edge. Return True on success, False if duplicate (same PK)."""
    try:
        conn.execute(
            """
            INSERT INTO edges (source_id, target_id, relation, weight, fact, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                edge.source_id,
                edge.target_id,
                edge.relation,
                _clamp_weight(edge.weight),
                edge.fact,
                datetime_to_iso(edge.created_at if edge.created_at is not None else utcnow()),
            ),
        )
    except sqlite3.IntegrityError as exc:
        message = str(exc)
        if "UNIQUE constraint failed" in message or "PRIMARY KEY" in message:
            if commit:
                conn.rollback()
            return False
        raise

    if commit:
        conn.commit()
    return True


def _get_edges_by_column(
    conn: sqlite3.Connection,
    *,
    column: Literal["source_id", "target_id"],
    node_id: str,
    relation: str | None = None,
) -> list[Edge]:
    query = f"SELECT * FROM edges WHERE {column} = ?"
    params: list[object] = [node_id]
    if relation is not None:
        query += " AND relation = ?"
        params.append(relation)
    query += " ORDER BY created_at ASC"
    rows = conn.execute(query, params).fetchall()
    return [row_to_edge(row) for row in rows]


def get_edges_from(conn: sqlite3.Connection, node_id: str, relation: str | None = None) -> list[Edge]:
    """All outgoing edges from a node. Optionally filter by relation."""
    return _get_edges_by_column(conn, column="source_id", node_id=node_id, relation=relation)


def get_edges_to(conn: sqlite3.Connection, node_id: str, relation: str | None = None) -> list[Edge]:
    """All incoming edges to a node. Optionally filter by relation."""
    return _get_edges_by_column(conn, column="target_id", node_id=node_id, relation=relation)


def get_edges_between(
    conn: sqlite3.Connection,
    node_ids: list[str],
    relations: list[str] | None = None,
) -> list[Edge]:
    """Find all edges where BOTH source_id and target_id are in node_ids."""
    if not node_ids:
        return []

    placeholders = ", ".join(["?"] * len(node_ids))
    params: list[object] = [*node_ids, *node_ids]
    query = (
        f"SELECT * FROM edges WHERE source_id IN ({placeholders}) "
        f"AND target_id IN ({placeholders})"
    )

    if relations:
        relation_placeholders = ", ".join(["?"] * len(relations))
        query += f" AND relation IN ({relation_placeholders})"
        params.extend(relations)

    query += " ORDER BY created_at ASC"
    rows = conn.execute(query, params).fetchall()
    return [row_to_edge(row) for row in rows]


def update_edge_weight(
    conn: sqlite3.Connection,
    source_id: str,
    target_id: str,
    relation: str,
    delta: float,
    *,
    commit: bool = True,
) -> None:
    """Adjust edge weight by delta, clamped to [0.0, 1.0]."""
    row = conn.execute(
        "SELECT weight FROM edges WHERE source_id = ? AND target_id = ? AND relation = ?",
        (source_id, target_id, relation),
    ).fetchone()
    if not row:
        return

    new_weight = _clamp_weight(row["weight"] + delta)
    conn.execute(
        "UPDATE edges SET weight = ? WHERE source_id = ? AND target_id = ? AND relation = ?",
        (new_weight, source_id, target_id, relation),
    )
    if commit:
        conn.commit()


def delete_edges_for_node(conn: sqlite3.Connection, node_id: str, *, commit: bool = True) -> None:
    """Explicitly delete all edges for a node. (CASCADE handles this too, but this is for logging.)"""
    conn.execute("DELETE FROM edges WHERE source_id = ? OR target_id = ?", (node_id, node_id))
    if commit:
        conn.commit()


__all__ = [
    "Edge",
    "create_edge",
    "delete_edges_for_node",
    "get_edges_between",
    "get_edges_from",
    "get_edges_to",
    "row_to_edge",
    "update_edge_weight",
]