from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from config import IMPORTANCE_DEFAULT, IMPORTANCE_MAX, IMPORTANCE_MIN
from pam.db.schema import datetime_to_iso, iso_to_datetime, resolve_workspace_id, utcnow


@dataclass
class Node:
    id: str
    type: Literal["event", "entity", "note", "source"]
    title: str
    content: str
    summary: str
    content_hash: str
    created_at: datetime
    valid_at: datetime
    updated_at: datetime
    tags: list[str]
    session_id: str | None
    importance: float
    access_count: int
    status: Literal["active", "draft", "reference", "archived"]
    metadata: dict
    workspace_id: str | None = None


UPDATABLE_FIELDS = {
    "type",
    "title",
    "content",
    "summary",
    "content_hash",
    "valid_at",
    "tags",
    "session_id",
    "importance",
    "access_count",
    "status",
    "metadata",
    "workspace_id",
}

NODE_COLUMNS = (
    "id",
    "type",
    "title",
    "content",
    "summary",
    "content_hash",
    "created_at",
    "valid_at",
    "updated_at",
    "tags",
    "session_id",
    "importance",
    "access_count",
    "status",
    "metadata",
    "workspace_id",
)


def _clamp_importance(value: float) -> float:
    return max(IMPORTANCE_MIN, min(IMPORTANCE_MAX, value))


def _serialize_tags(tags: list[str]) -> str:
    return json.dumps(tags or [])


def _deserialize_tags(value: str) -> list[str]:
    raw = json.loads(value or "[]")
    return raw if isinstance(raw, list) else []


def _serialize_metadata(metadata: dict) -> str:
    return json.dumps(metadata or {})


def _deserialize_metadata(value: str) -> dict:
    raw = json.loads(value or "{}")
    return raw if isinstance(raw, dict) else {}


def _serialize_node_field(field: str, value: object) -> object:
    if field in {"created_at", "valid_at", "updated_at"}:
        return datetime_to_iso(value)
    if field == "tags":
        return _serialize_tags(value)
    if field == "metadata":
        return _serialize_metadata(value)
    if field == "importance":
        return _clamp_importance(value)
    if field == "workspace_id":
        return resolve_workspace_id(value)
    return value


def _node_insert_values(node: Node, node_id: str) -> tuple[object, ...]:
    created_at = node.created_at if node.created_at is not None else utcnow()
    valid_at = node.valid_at if node.valid_at is not None else created_at
    updated_at = node.updated_at if node.updated_at is not None else created_at

    raw_values = {
        "id": node_id,
        "type": node.type,
        "title": node.title,
        "content": node.content,
        "summary": node.summary,
        "content_hash": node.content_hash,
        "created_at": created_at,
        "valid_at": valid_at,
        "updated_at": updated_at,
        "tags": node.tags,
        "session_id": node.session_id,
        "importance": node.importance if node.importance is not None else IMPORTANCE_DEFAULT,
        "access_count": node.access_count,
        "status": node.status,
        "metadata": node.metadata,
        "workspace_id": node.workspace_id,
    }
    return tuple(_serialize_node_field(column, raw_values[column]) for column in NODE_COLUMNS)


def _importance_update_params(node_id: str, importance: float, updated_at: str) -> tuple[object, ...]:
    return (_clamp_importance(importance), updated_at, node_id)


def row_to_node(row: sqlite3.Row) -> Node:
    row_keys = row.keys()
    return Node(
        id=row["id"],
        type=row["type"],
        title=row["title"],
        content=row["content"],
        summary=row["summary"],
        content_hash=row["content_hash"],
        created_at=iso_to_datetime(row["created_at"]),
        valid_at=iso_to_datetime(row["valid_at"]),
        updated_at=iso_to_datetime(row["updated_at"]),
        tags=_deserialize_tags(row["tags"]),
        session_id=row["session_id"],
        importance=row["importance"],
        access_count=row["access_count"],
        status=row["status"],
        metadata=_deserialize_metadata(row["metadata"]),
        workspace_id=row["workspace_id"] if "workspace_id" in row_keys else None,
    )


def create_node(conn: sqlite3.Connection, node: Node, *, commit: bool = True) -> str:
    """Insert a node. Generate UUID if node.id is empty. Return the ID."""
    node_id = node.id or str(uuid.uuid4())

    conn.execute(
        """
        INSERT INTO nodes (
            id, type, title, content, summary, content_hash,
            created_at, valid_at, updated_at, tags, session_id,
            importance, access_count, status, metadata, workspace_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        _node_insert_values(node, node_id),
    )
    if commit:
        conn.commit()
    return node_id


def get_node(conn: sqlite3.Connection, node_id: str) -> Node | None:
    """Fetch a single node by ID. Return None if not found."""
    row = conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
    return row_to_node(row) if row else None


def update_node(conn: sqlite3.Connection, node_id: str, *, commit: bool = True, **fields) -> bool:
    """Update specified fields. Always set updated_at = now(). Return True if row existed."""
    unexpected = set(fields) - UPDATABLE_FIELDS
    if unexpected:
        unexpected_fields = ", ".join(sorted(unexpected))
        raise ValueError(f"Unsupported node fields: {unexpected_fields}")

    assignments: list[str] = []
    params: list[object] = []
    for field, value in fields.items():
        value = _serialize_node_field(field, value)
        assignments.append(f"{field} = ?")
        params.append(value)

    assignments.append("updated_at = ?")
    params.append(datetime_to_iso(utcnow()))
    params.append(node_id)

    cursor = conn.execute(
        f"UPDATE nodes SET {', '.join(assignments)} WHERE id = ?",
        params,
    )
    if commit:
        conn.commit()
    return cursor.rowcount > 0


def delete_node(conn: sqlite3.Connection, node_id: str, *, commit: bool = True) -> bool:
    """Delete a node. CASCADE removes edges. Return True if row existed."""
    cursor = conn.execute("DELETE FROM nodes WHERE id = ?", (node_id,))
    if commit:
        conn.commit()
    return cursor.rowcount > 0


def list_nodes(
    conn: sqlite3.Connection,
    type: str | None = None,
    status: str | None = None,
    session_id: str | None = None,
    workspace_id: str | None = None,
    since: datetime | None = None,
    limit: int | None = 100,
) -> list[Node]:
    """Filter and list nodes. 'since' filters on valid_at."""
    clauses: list[str] = []
    params: list[object] = []

    if type is not None:
        clauses.append("type = ?")
        params.append(type)
    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    if session_id is not None:
        clauses.append("session_id = ?")
        params.append(session_id)
    if workspace_id is not None:
        clauses.append("workspace_id = ?")
        params.append(resolve_workspace_id(workspace_id))
    if since is not None:
        clauses.append("valid_at >= ?")
        params.append(datetime_to_iso(since))

    where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    query = f"SELECT * FROM nodes {where_clause} ORDER BY valid_at DESC, created_at DESC"

    if limit is not None:
        params.append(max(1, limit))
        query += " LIMIT ?"

    rows = conn.execute(query, params).fetchall()
    return [row_to_node(row) for row in rows]


def find_by_content_hash(conn: sqlite3.Connection, content_hash: str, workspace_id: str | None = None) -> Node | None:
    """Dedup lookup. Return first active/draft/reference node with this hash, or None."""
    query = """
        SELECT *
        FROM nodes
        WHERE content_hash = ?
          AND status IN ('active', 'draft', 'reference')
    """
    params: list[object] = [content_hash]
    if workspace_id is not None:
        query += " AND workspace_id = ?"
        params.append(resolve_workspace_id(workspace_id))
    query += " ORDER BY created_at ASC LIMIT 1"
    row = conn.execute(query, params).fetchone()
    return row_to_node(row) if row else None


def increment_access_count(conn: sqlite3.Connection, node_id: str, *, commit: bool = True) -> None:
    """Atomically increment access_count by 1."""
    conn.execute("UPDATE nodes SET access_count = access_count + 1 WHERE id = ?", (node_id,))
    if commit:
        conn.commit()


def update_importance(conn: sqlite3.Connection, node_id: str, new_importance: float, *, commit: bool = True) -> None:
    """Set importance, clamped to [0.0, 1.0]. Update updated_at."""
    updated_at = datetime_to_iso(utcnow())
    conn.execute(
        "UPDATE nodes SET importance = ?, updated_at = ? WHERE id = ?",
        _importance_update_params(node_id, new_importance, updated_at),
    )
    if commit:
        conn.commit()


def bulk_update_importance(conn: sqlite3.Connection, updates: list[tuple[str, float]], *, commit: bool = True) -> None:
    """Batch update importance for decay. Each tuple is (node_id, new_importance)."""
    if not updates:
        return

    updated_at = datetime_to_iso(utcnow())
    conn.executemany(
        "UPDATE nodes SET importance = ?, updated_at = ? WHERE id = ?",
        [_importance_update_params(node_id, importance, updated_at) for node_id, importance in updates],
    )
    if commit:
        conn.commit()


__all__ = [
    "Node",
    "bulk_update_importance",
    "create_node",
    "delete_node",
    "find_by_content_hash",
    "get_node",
    "increment_access_count",
    "list_nodes",
    "row_to_node",
    "update_importance",
    "update_node",
]