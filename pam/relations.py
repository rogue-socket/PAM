"""Centralized side-effect logic for relation writes that mutate node state.

Both the explicit feedback path (`pam.feedback.supersede`) and the ingest-cue
path (`pam.ingestion.pipeline._infer_explicit_cross_memory_relations`) need to
apply the same node-state changes when a SUPERSEDES edge is asserted. Keeping
that logic in one place is what closes audit O3.
"""
from __future__ import annotations

import sqlite3

from config import IMPORTANCE_MIN, LOG_PATH, SUPERSEDE_IMPORTANCE_FACTOR
from pam.db import transaction
from pam.db.edges import Edge, create_edge
from pam.db.nodes import Node, update_importance, update_node
from pam.db.schema import utcnow, utcnow_iso


def apply_supersedes(
    conn: sqlite3.Connection,
    *,
    new_node_id: str,
    old_node: Node,
    fact: str,
    source: str,
) -> bool:
    """Write a SUPERSEDES edge and apply unified node-state side effects.

    Side effects (idempotent across replays):
    - Always creates the edge (or no-op if a duplicate by primary key already exists).
    - Always sets `old_node.status = "reference"`. Idempotent at the status level.
    - Dampens `old_node.importance` by `SUPERSEDE_IMPORTANCE_FACTOR` only on the
      first creation, so replay does not multiply the dampening.
    - Logs a `supersede` lifecycle event with `source` set to "user" or
      "ingest_cue", and `edge_created` distinguishing first vs replay.

    Returns True if the edge was newly created (i.e., this was the first
    application), False if it was a duplicate.
    """
    with transaction(conn):
        created = create_edge(
            conn,
            Edge(
                source_id=new_node_id,
                target_id=old_node.id,
                relation="SUPERSEDES",
                weight=1.0,
                fact=fact,
                created_at=utcnow(),
            ),
            commit=False,
        )

        old_importance = old_node.importance
        new_importance = old_importance
        if created:
            new_importance = max(old_importance * SUPERSEDE_IMPORTANCE_FACTOR, IMPORTANCE_MIN)
            update_importance(conn, old_node.id, new_importance, commit=False)

        update_node(conn, old_node.id, status="reference", commit=False)

    _log_supersede(
        new_node_id=new_node_id,
        old_node_id=old_node.id,
        old_importance=old_importance,
        new_importance=new_importance,
        edge_created=created,
        source=source,
    )
    return created


def _log_supersede(
    *,
    new_node_id: str,
    old_node_id: str,
    old_importance: float,
    new_importance: float,
    edge_created: bool,
    source: str,
) -> None:
    from pam.telemetry import append_log_line

    append_log_line(
        LOG_PATH,
        {
            "ts": utcnow_iso(),
            "event": "supersede",
            "new_node_id": new_node_id,
            "old_node_id": old_node_id,
            "old_importance": old_importance,
            "new_importance": new_importance,
            "edge_created": edge_created,
            "source": source,
        },
    )


__all__ = ["apply_supersedes"]
