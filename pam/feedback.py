from __future__ import annotations

import sqlite3

from config import (
    DOWNVOTE_DELTA,
    EDGE_UPVOTE_DELTA,
    IMPORTANCE_MAX,
    IMPORTANCE_MIN,
    LOG_PATH,
    UPVOTE_DELTA,
)
from pam.db import transaction
from pam.db.edges import update_edge_weight
from pam.db.nodes import Node, get_node, update_importance
from pam.db.schema import utcnow_iso
from pam.relations import apply_supersedes


SUPERSEDE_TYPES = {"note", "entity"}


def _append_log(payload: dict) -> None:
    from pam.telemetry import append_log_line

    record = {"ts": utcnow_iso(), **payload}
    append_log_line(LOG_PATH, record)


def _update_importance_with_log(
    conn: sqlite3.Connection,
    *,
    node: Node,
    node_id: str,
    event: str,
    new_importance: float,
    extra_payload: dict | None = None,
) -> None:
    update_importance(conn, node_id, new_importance)
    payload = {
        "event": event,
        "node_id": node_id,
        "old_importance": node.importance,
        "new_importance": new_importance,
    }
    if extra_payload:
        payload.update(extra_payload)
    _append_log(payload)


def upvote(
    conn: sqlite3.Connection,
    node_id: str,
    edge_ids: list[tuple[str, str, str]] | None = None,
) -> bool:
    node = get_node(conn, node_id)
    if not node:
        return False

    new_importance = min(node.importance + UPVOTE_DELTA, IMPORTANCE_MAX)

    with transaction(conn):
        for source_id, target_id, relation in edge_ids or []:
            update_edge_weight(conn, source_id, target_id, relation, EDGE_UPVOTE_DELTA, commit=False)
        update_importance(conn, node_id, new_importance, commit=False)

    _append_log(
        {
            "event": "upvote",
            "node_id": node_id,
            "old_importance": node.importance,
            "new_importance": new_importance,
            "edges_boosted": len(edge_ids or []),
        }
    )
    return True


def downvote(conn: sqlite3.Connection, node_id: str) -> bool:
    node = get_node(conn, node_id)
    if not node:
        return False

    new_importance = max(node.importance + DOWNVOTE_DELTA, IMPORTANCE_MIN)
    _update_importance_with_log(
        conn,
        node=node,
        node_id=node_id,
        event="downvote",
        new_importance=new_importance,
    )
    return True


def pin(conn: sqlite3.Connection, node_id: str) -> bool:
    node = get_node(conn, node_id)
    if not node:
        return False

    _update_importance_with_log(
        conn,
        node=node,
        node_id=node_id,
        event="pin",
        new_importance=IMPORTANCE_MAX,
    )
    return True


def supersede(conn: sqlite3.Connection, new_node_id: str, old_node_id: str) -> bool:
    new_node = get_node(conn, new_node_id)
    old_node = get_node(conn, old_node_id)
    if not new_node or not old_node:
        return False
    if new_node.type not in SUPERSEDE_TYPES or old_node.type not in SUPERSEDE_TYPES:
        return False

    apply_supersedes(
        conn,
        new_node_id=new_node_id,
        old_node=old_node,
        fact="",
        source="user",
    )
    return True


__all__ = ["downvote", "pin", "supersede", "upvote"]