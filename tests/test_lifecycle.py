from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from math import exp
from pathlib import Path

import json

import pam.feedback as feedback_module
import pam.lifecycle as lifecycle_module
import pam.relations as relations_module
from config import ARCHIVE_THRESHOLD, DECAY_LAMBDA, IMPORTANCE_DEFAULT
from pam.db.edges import Edge, create_edge, get_edges_from
from pam.db.nodes import Node, create_node, get_node
from pam.db.schema import datetime_to_iso, get_connection, initialize
from pam.feedback import downvote, pin, supersede, upvote
from pam.lifecycle import apply_decay, unarchive


def make_node(
    *,
    node_id: str = "",
    node_type: str = "note",
    title: str = "Example",
    content: str = "",
    summary: str = "",
    content_hash: str = "",
    valid_at: datetime | None = None,
    tags: list[str] | None = None,
    session_id: str | None = None,
    importance: float = 0.5,
    access_count: int = 0,
    status: str = "active",
    metadata: dict | None = None,
) -> Node:
    timestamp = valid_at or datetime.now(timezone.utc)
    return Node(
        id=node_id,
        type=node_type,
        title=title,
        content=content,
        summary=summary,
        content_hash=content_hash,
        created_at=timestamp,
        valid_at=timestamp,
        updated_at=timestamp,
        tags=tags or [],
        session_id=session_id,
        importance=importance,
        access_count=access_count,
        status=status,
        metadata=metadata or {},
    )


def make_edge(source_id: str, target_id: str, relation: str = "RELATED", weight: float = 1.0) -> Edge:
    return Edge(
        source_id=source_id,
        target_id=target_id,
        relation=relation,
        weight=weight,
        fact="",
        created_at=datetime.now(timezone.utc),
    )


class LifecycleModuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = get_connection(":memory:")
        initialize(self.conn)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.log_path = Path(self.temp_dir.name) / "pam_log.jsonl"
        self.original_lifecycle_log_path = lifecycle_module.LOG_PATH
        self.original_feedback_log_path = feedback_module.LOG_PATH
        self.original_relations_log_path = relations_module.LOG_PATH
        lifecycle_module.LOG_PATH = self.log_path
        feedback_module.LOG_PATH = self.log_path
        relations_module.LOG_PATH = self.log_path

    def tearDown(self) -> None:
        lifecycle_module.LOG_PATH = self.original_lifecycle_log_path
        feedback_module.LOG_PATH = self.original_feedback_log_path
        relations_module.LOG_PATH = self.original_relations_log_path
        self.temp_dir.cleanup()
        self.conn.close()

    def set_updated_at(self, node_id: str, updated_at: datetime) -> None:
        self.conn.execute(
            "UPDATE nodes SET updated_at = ? WHERE id = ?",
            (datetime_to_iso(updated_at), node_id),
        )
        self.conn.commit()

    def test_decay_basic(self) -> None:
        node_id = create_node(self.conn, make_node(importance=0.5))
        self.set_updated_at(node_id, datetime.now(timezone.utc) - timedelta(days=100))

        result = apply_decay(self.conn)
        node = get_node(self.conn, node_id)

        self.assertIsNotNone(node)
        assert node is not None
        self.assertEqual(result["nodes_decayed"], 1)
        self.assertAlmostEqual(node.importance, 0.5 * exp(-DECAY_LAMBDA * 100), places=6)

    def test_decay_pinned_nodes_are_immune(self) -> None:
        node_id = create_node(self.conn, make_node(importance=1.0))
        self.set_updated_at(node_id, datetime.now(timezone.utc) - timedelta(days=365))

        result = apply_decay(self.conn)
        node = get_node(self.conn, node_id)

        self.assertIsNotNone(node)
        assert node is not None
        self.assertEqual(result["skipped_pinned"], 1)
        self.assertEqual(result["nodes_decayed"], 0)
        self.assertEqual(node.importance, 1.0)

    def test_decay_recently_updated_node_is_unchanged(self) -> None:
        node_id = create_node(self.conn, make_node(importance=0.5))

        result = apply_decay(self.conn)
        node = get_node(self.conn, node_id)

        self.assertIsNotNone(node)
        assert node is not None
        self.assertEqual(result["nodes_decayed"], 0)
        self.assertEqual(node.importance, 0.5)

    def test_decay_archives_nodes_below_threshold(self) -> None:
        node_id = create_node(self.conn, make_node(importance=ARCHIVE_THRESHOLD, status="active"))
        self.set_updated_at(node_id, datetime.now(timezone.utc) - timedelta(days=1))

        result = apply_decay(self.conn)
        node = get_node(self.conn, node_id)

        self.assertIsNotNone(node)
        assert node is not None
        self.assertEqual(result["nodes_archived"], 1)
        self.assertEqual(node.status, "archived")
        self.assertLess(node.importance, ARCHIVE_THRESHOLD)

    def test_decay_excludes_already_archived_nodes(self) -> None:
        node_id = create_node(self.conn, make_node(importance=0.01, status="archived"))
        self.set_updated_at(node_id, datetime.now(timezone.utc) - timedelta(days=365))

        result = apply_decay(self.conn)
        node = get_node(self.conn, node_id)

        self.assertIsNotNone(node)
        assert node is not None
        self.assertEqual(result["nodes_processed"], 0)
        self.assertEqual(result["nodes_decayed"], 0)
        self.assertEqual(node.status, "archived")
        self.assertEqual(node.importance, 0.01)

    def test_unarchive_restores_archived_node(self) -> None:
        node_id = create_node(self.conn, make_node(importance=0.01, status="archived"))

        self.assertTrue(unarchive(self.conn, node_id))

        node = get_node(self.conn, node_id)
        self.assertIsNotNone(node)
        assert node is not None
        self.assertEqual(node.status, "active")
        self.assertEqual(node.importance, IMPORTANCE_DEFAULT)

    def test_unarchive_rejects_non_archived_node(self) -> None:
        node_id = create_node(self.conn, make_node(status="active"))
        self.assertFalse(unarchive(self.conn, node_id))

    def test_upvote_increases_importance(self) -> None:
        node_id = create_node(self.conn, make_node(importance=0.5))

        self.assertTrue(upvote(self.conn, node_id))

        node = get_node(self.conn, node_id)
        self.assertIsNotNone(node)
        assert node is not None
        self.assertEqual(node.importance, 0.6)

    def test_upvote_is_capped(self) -> None:
        node_id = create_node(self.conn, make_node(importance=0.95))

        self.assertTrue(upvote(self.conn, node_id))

        node = get_node(self.conn, node_id)
        self.assertIsNotNone(node)
        assert node is not None
        self.assertEqual(node.importance, 1.0)

    def test_upvote_boosts_edges(self) -> None:
        node_id = create_node(self.conn, make_node(title="Node"))
        target_id = create_node(self.conn, make_node(title="Target", node_type="entity"))
        create_edge(self.conn, make_edge(node_id, target_id, weight=0.4))

        self.assertTrue(upvote(self.conn, node_id, [(node_id, target_id, "RELATED")]))

        edge = get_edges_from(self.conn, node_id)[0]
        self.assertEqual(edge.weight, 0.45)

    def test_downvote_decreases_importance(self) -> None:
        node_id = create_node(self.conn, make_node(importance=0.5))

        self.assertTrue(downvote(self.conn, node_id))

        node = get_node(self.conn, node_id)
        self.assertIsNotNone(node)
        assert node is not None
        self.assertEqual(node.importance, 0.4)

    def test_downvote_is_floored(self) -> None:
        node_id = create_node(self.conn, make_node(importance=0.05))

        self.assertTrue(downvote(self.conn, node_id))

        node = get_node(self.conn, node_id)
        self.assertIsNotNone(node)
        assert node is not None
        self.assertEqual(node.importance, 0.0)

    def test_downvote_does_not_change_edges(self) -> None:
        node_id = create_node(self.conn, make_node(title="Node"))
        target_id = create_node(self.conn, make_node(title="Target", node_type="entity"))
        create_edge(self.conn, make_edge(node_id, target_id, weight=0.4))

        self.assertTrue(downvote(self.conn, node_id))

        edge = get_edges_from(self.conn, node_id)[0]
        self.assertEqual(edge.weight, 0.4)

    def test_pin_sets_importance_to_maximum(self) -> None:
        node_id = create_node(self.conn, make_node(importance=0.2))

        self.assertTrue(pin(self.conn, node_id))

        node = get_node(self.conn, node_id)
        self.assertIsNotNone(node)
        assert node is not None
        self.assertEqual(node.importance, 1.0)

    def test_supersede_creates_edge_and_demotes_old_node(self) -> None:
        old_node_id = create_node(self.conn, make_node(importance=0.6, title="Old"))
        new_node_id = create_node(self.conn, make_node(importance=0.5, title="New"))

        self.assertTrue(supersede(self.conn, new_node_id, old_node_id))

        old_node = get_node(self.conn, old_node_id)
        self.assertIsNotNone(old_node)
        assert old_node is not None
        supersedes_edges = get_edges_from(self.conn, new_node_id, relation="SUPERSEDES")
        self.assertEqual(len(supersedes_edges), 1)
        self.assertEqual(supersedes_edges[0].target_id, old_node_id)
        self.assertEqual(old_node.status, "reference")
        self.assertEqual(old_node.importance, 0.3)

    def test_supersede_returns_false_for_missing_nodes(self) -> None:
        node_id = create_node(self.conn, make_node(title="Present"))
        self.assertFalse(supersede(self.conn, node_id, "missing-node"))

    def test_supersede_rejects_invalid_node_types(self) -> None:
        event_id = create_node(self.conn, make_node(node_type="event", title="Event"))
        source_id = create_node(self.conn, make_node(node_type="source", title="Source"))

        self.assertFalse(supersede(self.conn, event_id, source_id))
        self.assertEqual(get_edges_from(self.conn, event_id, relation="SUPERSEDES"), [])

        source_node = get_node(self.conn, source_id)
        self.assertIsNotNone(source_node)
        assert source_node is not None
        self.assertEqual(source_node.status, "active")
        self.assertEqual(source_node.importance, 0.5)

    def test_supersede_replay_does_not_re_dampen_importance(self) -> None:
        """O3: replaying supersede on the same pair must not multiply importance twice."""
        old_id = create_node(self.conn, make_node(importance=0.6, title="Old"))
        new_id = create_node(self.conn, make_node(importance=0.5, title="New"))

        self.assertTrue(supersede(self.conn, new_id, old_id))
        first_pass = get_node(self.conn, old_id)
        assert first_pass is not None
        self.assertAlmostEqual(first_pass.importance, 0.3)

        # Replay: edge already exists. Importance must stay 0.3, not drop to 0.15.
        self.assertTrue(supersede(self.conn, new_id, old_id))
        second_pass = get_node(self.conn, old_id)
        assert second_pass is not None
        self.assertAlmostEqual(second_pass.importance, 0.3)
        self.assertEqual(second_pass.status, "reference")
        self.assertEqual(len(get_edges_from(self.conn, new_id, relation="SUPERSEDES")), 1)

    def test_supersede_telemetry_records_source_and_edge_created(self) -> None:
        """O3: log payload distinguishes user vs ingest_cue and first-vs-replay."""
        old_id = create_node(self.conn, make_node(importance=0.6, title="Old"))
        new_id = create_node(self.conn, make_node(importance=0.5, title="New"))

        supersede(self.conn, new_id, old_id)
        supersede(self.conn, new_id, old_id)

        events = [
            json.loads(line)
            for line in self.log_path.read_text().splitlines()
            if line.strip()
        ]
        supersede_events = [e for e in events if e.get("event") == "supersede"]
        self.assertEqual(len(supersede_events), 2)
        for evt in supersede_events:
            self.assertEqual(evt["source"], "user")
        self.assertTrue(supersede_events[0]["edge_created"])
        self.assertFalse(supersede_events[1]["edge_created"])


if __name__ == "__main__":
    unittest.main()