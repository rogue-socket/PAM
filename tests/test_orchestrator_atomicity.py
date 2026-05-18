"""Failure-injection tests for the supersede / decay / upvote orchestrators.

Each test mocks a downstream mutator to raise mid-orchestrator and
asserts that the partial writes were rolled back.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from pam.db.edges import Edge, create_edge, get_edges_between
from pam.db.nodes import Node, create_node, get_node
from pam.db.schema import get_connection, initialize
from pam.feedback import upvote
from pam.lifecycle import apply_decay
from pam.relations import apply_supersedes


def _node(*, title: str, suffix: str = "", importance: float = 0.6, status: str = "active", updated_offset_days: int = 0) -> Node:
    now = datetime.now(timezone.utc)
    updated = now - timedelta(days=updated_offset_days)
    return Node(
        id="",
        type="note",
        title=title,
        content=f"content for {title}",
        summary="",
        content_hash=f"{title}-{suffix}-hash",
        created_at=now,
        valid_at=now,
        updated_at=updated,
        tags=[],
        session_id=None,
        importance=importance,
        access_count=0,
        status=status,
        metadata={},
        workspace_id="ws-test",
    )


class SupersedeAtomicityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = get_connection(":memory:")
        initialize(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def test_failure_rolls_back_edge_and_importance(self) -> None:
        new_id = create_node(self.conn, _node(title="new", importance=0.6))
        old_id = create_node(self.conn, _node(title="old", importance=0.6))
        old_node = get_node(self.conn, old_id)
        baseline_importance = old_node.importance

        # Fail on the final update_node (status="reference"). The edge
        # and the dampened importance should both roll back.
        with mock.patch(
            "pam.relations.update_node",
            side_effect=RuntimeError("boom-on-status-update"),
        ):
            with self.assertRaises(RuntimeError):
                apply_supersedes(
                    self.conn,
                    new_node_id=new_id,
                    old_node=old_node,
                    fact="",
                    source="user",
                )

        post = get_node(self.conn, old_id)
        self.assertEqual(post.status, "active", "status should not have flipped")
        self.assertEqual(post.importance, baseline_importance, "importance dampening should be rolled back")
        edges = get_edges_between(self.conn, [new_id, old_id], relations=["SUPERSEDES"])
        self.assertEqual(edges, [], "SUPERSEDES edge should be rolled back")


class DecayAtomicityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = get_connection(":memory:")
        initialize(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def test_failure_in_archive_rolls_back_bulk_importance(self) -> None:
        # Create nodes old enough to decay below the archive threshold.
        # Settings chosen to decay below ARCHIVE_THRESHOLD (0.05):
        # 0.1 * exp(-0.005 * 200) = 0.0368 → triggers archive.
        ids = [
            create_node(self.conn, _node(title=f"old-{i}", importance=0.1, updated_offset_days=200))
            for i in range(3)
        ]
        baseline = {nid: get_node(self.conn, nid).importance for nid in ids}

        with mock.patch(
            "pam.lifecycle.update_node",
            side_effect=RuntimeError("boom-in-archive"),
        ):
            with self.assertRaises(RuntimeError):
                apply_decay(self.conn)

        for nid in ids:
            node = get_node(self.conn, nid)
            self.assertEqual(node.importance, baseline[nid], f"importance for {nid} should be rolled back")
            self.assertEqual(node.status, "active", f"status for {nid} should still be active")


class UpvoteAtomicityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = get_connection(":memory:")
        initialize(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def test_failure_after_edge_boost_rolls_back_edge(self) -> None:
        src = create_node(self.conn, _node(title="src", importance=0.5))
        tgt = create_node(self.conn, _node(title="tgt", importance=0.5))
        edge = Edge(
            source_id=src,
            target_id=tgt,
            relation="RELATED",
            weight=0.5,
            fact="",
            created_at=datetime.now(timezone.utc),
        )
        create_edge(self.conn, edge)
        baseline_edge = get_edges_between(self.conn, [src, tgt], relations=["RELATED"])[0]
        baseline_importance = get_node(self.conn, src).importance

        with mock.patch(
            "pam.feedback.update_importance",
            side_effect=RuntimeError("boom-on-importance"),
        ):
            with self.assertRaises(RuntimeError):
                upvote(self.conn, src, edge_ids=[(src, tgt, "RELATED")])

        post_edge = get_edges_between(self.conn, [src, tgt], relations=["RELATED"])[0]
        post_importance = get_node(self.conn, src).importance
        self.assertEqual(post_edge.weight, baseline_edge.weight, "edge weight boost should be rolled back")
        self.assertEqual(post_importance, baseline_importance, "node importance bump should be rolled back")


if __name__ == "__main__":
    unittest.main()
