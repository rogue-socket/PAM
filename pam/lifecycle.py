from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from math import exp
from time import perf_counter

from config import ARCHIVE_THRESHOLD, DECAY_LAMBDA, IMPORTANCE_DEFAULT, IMPORTANCE_MAX, IMPORTANCE_MIN, LOG_PATH
from pam.db.nodes import Node, bulk_update_importance, get_node, list_nodes, update_node
from pam.db.schema import utcnow, utcnow_iso


ELIGIBLE_STATUSES = {"active", "draft", "reference"}


def _append_log(payload: dict) -> None:
    record = {"ts": utcnow_iso(), **payload}
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


def compute_decayed_importance(node: Node, now: datetime) -> float:
    if node.importance == IMPORTANCE_MAX:
        return IMPORTANCE_MAX

    days = (now - node.updated_at).days
    if days <= 0:
        return node.importance

    new_importance = node.importance * exp(-DECAY_LAMBDA * days)
    return max(new_importance, IMPORTANCE_MIN)


def _eligible_nodes(conn: sqlite3.Connection) -> list[Node]:
    return [node for node in list_nodes(conn, limit=None) if node.status in ELIGIBLE_STATUSES]


def _plan_decay_updates(nodes: list[Node], now: datetime) -> tuple[list[tuple[str, float]], int]:
    skipped_pinned = 0
    updates: list[tuple[str, float]] = []

    for node in nodes:
        if node.importance == IMPORTANCE_MAX:
            skipped_pinned += 1
            continue

        new_importance = compute_decayed_importance(node, now)
        if new_importance != node.importance:
            updates.append((node.id, new_importance))

    return updates, skipped_pinned


def _archive_decayed_nodes(conn: sqlite3.Connection, updates: list[tuple[str, float]]) -> int:
    archived_count = 0
    for node_id, new_importance in updates:
        if new_importance >= ARCHIVE_THRESHOLD:
            continue

        update_node(conn, node_id, status="archived")
        archived_count += 1
        _append_log(
            {
                "event": "archive",
                "node_id": node_id,
                "final_importance": new_importance,
            }
        )

    return archived_count


def apply_decay(conn: sqlite3.Connection) -> dict[str, int]:
    started = perf_counter()
    now = utcnow()
    eligible_nodes = _eligible_nodes(conn)
    updates, skipped_pinned = _plan_decay_updates(eligible_nodes, now)

    bulk_update_importance(conn, updates)
    archived_count = _archive_decayed_nodes(conn, updates)

    summary = {
        "nodes_processed": len(eligible_nodes),
        "nodes_decayed": len(updates),
        "nodes_archived": archived_count,
        "skipped_pinned": skipped_pinned,
    }
    _append_log(
        {
            "event": "decay",
            **summary,
            "duration_ms": round((perf_counter() - started) * 1000),
        }
    )
    return summary


def unarchive(conn: sqlite3.Connection, node_id: str) -> bool:
    node = get_node(conn, node_id)
    if not node or node.status != "archived":
        return False

    update_node(conn, node_id, status="active", importance=IMPORTANCE_DEFAULT)
    return True


__all__ = ["apply_decay", "compute_decayed_importance", "unarchive"]