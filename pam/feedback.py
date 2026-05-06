from __future__ import annotations

import json
import sqlite3

from config import (
    DOWNVOTE_DELTA,
    EDGE_UPVOTE_DELTA,
    IMPORTANCE_MAX,
    IMPORTANCE_MIN,
    LOG_PATH,
    SUPERSEDE_IMPORTANCE_FACTOR,
    UPVOTE_DELTA,
)
from pam.db.edges import Edge, create_edge, update_edge_weight
from pam.db.nodes import Node, get_node, update_importance, update_node
from pam.db.schema import utcnow, utcnow_iso


SUPERSEDE_TYPES = {"note", "entity"}


def _append_log(payload: dict) -> None:
    record = {"ts": utcnow_iso(), **payload}
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


def _get_feedback_node(conn: sqlite3.Connection, node_id: str) -> Node | None:
    return get_node(conn, node_id)


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
    node = _get_feedback_node(conn, node_id)
    if not node:
        return False

    new_importance = min(node.importance + UPVOTE_DELTA, IMPORTANCE_MAX)

    for source_id, target_id, relation in edge_ids or []:
        update_edge_weight(conn, source_id, target_id, relation, EDGE_UPVOTE_DELTA)

    _update_importance_with_log(
        conn,
        node=node,
        node_id=node_id,
        event="upvote",
        new_importance=new_importance,
        extra_payload={"edges_boosted": len(edge_ids or [])},
    )
    return True


def downvote(conn: sqlite3.Connection, node_id: str) -> bool:
    node = _get_feedback_node(conn, node_id)
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
    node = _get_feedback_node(conn, node_id)
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
    new_node = _get_feedback_node(conn, new_node_id)
    old_node = _get_feedback_node(conn, old_node_id)
    if not new_node or not old_node:
        return False
    if new_node.type not in SUPERSEDE_TYPES or old_node.type not in SUPERSEDE_TYPES:
        return False

    created = create_edge(
        conn,
        Edge(
            source_id=new_node_id,
            target_id=old_node_id,
            relation="SUPERSEDES",
            weight=1.0,
            fact="",
            created_at=utcnow(),
        ),
    )

    old_importance = old_node.importance
    new_importance = old_importance
    if created:
        new_importance = max(old_importance * SUPERSEDE_IMPORTANCE_FACTOR, IMPORTANCE_MIN)
        update_importance(conn, old_node_id, new_importance)

    update_node(conn, old_node_id, status="reference")
    _append_log(
        {
            "event": "supersede",
            "new_node_id": new_node_id,
            "old_node_id": old_node_id,
            "old_importance": old_importance,
            "new_importance": new_importance,
            "edge_created": created,
        }
    )
    return True


__all__ = ["downvote", "pin", "supersede", "upvote"]