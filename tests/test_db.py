from __future__ import annotations

import logging
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from pam.db.edges import Edge, create_edge, get_edges_between, get_edges_from, get_edges_to, update_edge_weight
from pam.db.fts import fts_search
from pam.db.nodes import Node, bulk_update_importance, create_node, delete_node, find_by_content_hash, get_node, increment_access_count, list_nodes, update_importance, update_node
from pam.db import schema as schema_module
from pam.db.schema import get_connection, get_current_version, get_initialized_connection, initialize


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


class DatabaseModuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = get_connection(":memory:")
        initialize(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def test_schema_init_creates_all_tables_and_sets_version(self) -> None:
        tables = {
            row["name"]
            for row in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'trigger')"
            ).fetchall()
        }

        self.assertIn("schema_version", tables)
        self.assertIn("nodes", tables)
        self.assertIn("edges", tables)
        self.assertIn("fts_index", tables)
        self.assertIn("nodes_ai", tables)
        self.assertIn("nodes_au", tables)
        self.assertIn("nodes_ad", tables)
        self.assertEqual(get_current_version(self.conn), 2)

    def test_node_crud_round_trip_and_filters(self) -> None:
        node_id = create_node(
            self.conn,
            make_node(
                title="Original title",
                content="search text",
                tags=["db"],
                session_id="session-1",
            ),
        )

        fetched = get_node(self.conn, node_id)
        self.assertIsNotNone(fetched)
        assert fetched is not None
        original_updated_at = fetched.updated_at

        self.assertTrue(update_node(self.conn, node_id, title="Updated title", metadata={"source": "test"}))

        updated = get_node(self.conn, node_id)
        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated.title, "Updated title")
        self.assertEqual(updated.metadata, {"source": "test"})
        self.assertNotEqual(updated.updated_at, original_updated_at)

        increment_access_count(self.conn, node_id)
        incremented = get_node(self.conn, node_id)
        self.assertIsNotNone(incremented)
        assert incremented is not None
        self.assertEqual(incremented.access_count, 1)

        listed = list_nodes(self.conn, type="note", status="active", session_id="session-1")
        self.assertEqual([node.id for node in listed], [node_id])

        self.assertTrue(delete_node(self.conn, node_id))
        self.assertIsNone(get_node(self.conn, node_id))

    def test_create_node_preserves_provided_timestamps(self) -> None:
        created_at = datetime(2020, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
        valid_at = datetime(2020, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        updated_at = datetime(2020, 1, 3, 9, 30, 0, tzinfo=timezone.utc)

        custom_node_id = create_node(
            self.conn,
            Node(
                id="",
                type="note",
                title="Custom timestamps",
                content="",
                summary="",
                content_hash="",
                created_at=created_at,
                valid_at=valid_at,
                updated_at=updated_at,
                tags=[],
                session_id=None,
                importance=0.5,
                access_count=0,
                status="active",
                metadata={},
            ),
        )

        stored = get_node(self.conn, custom_node_id)
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored.created_at, created_at)
        self.assertEqual(stored.valid_at, valid_at)
        self.assertEqual(stored.updated_at, updated_at)

    def test_edge_crud_and_cascade_delete(self) -> None:
        source_id = create_node(self.conn, make_node(title="Source"))
        target_id = create_node(self.conn, make_node(title="Target", node_type="entity"))
        third_id = create_node(self.conn, make_node(title="Third", node_type="entity"))

        created = create_edge(self.conn, make_edge(source_id, target_id, relation="REFERS_TO"))
        self.assertTrue(created)
        self.assertFalse(create_edge(self.conn, make_edge(source_id, target_id, relation="REFERS_TO")))

        outgoing = get_edges_from(self.conn, source_id)
        incoming = get_edges_to(self.conn, target_id)
        between = get_edges_between(self.conn, [source_id, target_id, third_id])

        self.assertEqual(len(outgoing), 1)
        self.assertEqual(len(incoming), 1)
        self.assertEqual(len(between), 1)
        self.assertEqual(outgoing[0].target_id, target_id)
        self.assertEqual(incoming[0].source_id, source_id)

        delete_node(self.conn, source_id)
        self.assertEqual(get_edges_from(self.conn, source_id), [])
        self.assertEqual(get_edges_to(self.conn, target_id), [])

    def test_duplicate_edge_insert_leaves_connection_usable(self) -> None:
        source_id = create_node(self.conn, make_node(title="Source"))
        target_id = create_node(self.conn, make_node(title="Target", node_type="entity"))
        third_id = create_node(self.conn, make_node(title="Third", node_type="entity"))

        self.assertTrue(create_edge(self.conn, make_edge(source_id, target_id, relation="REFERS_TO")))
        self.assertFalse(create_edge(self.conn, make_edge(source_id, target_id, relation="REFERS_TO")))
        self.assertTrue(create_edge(self.conn, make_edge(source_id, third_id, relation="REFERS_TO")))

        outgoing = get_edges_from(self.conn, source_id, relation="REFERS_TO")
        self.assertEqual({edge.target_id for edge in outgoing}, {target_id, third_id})

    def test_fts_sync_tracks_insert_update_and_delete(self) -> None:
        node_id = create_node(self.conn, make_node(title="Alpha Title", content="", summary=""))

        inserted = fts_search(self.conn, "Alpha")
        self.assertEqual(len(inserted), 1)
        self.assertEqual(inserted[0][0].id, node_id)

        update_node(self.conn, node_id, title="Beta Title")

        updated = fts_search(self.conn, "Beta")
        old_results = fts_search(self.conn, "Alpha")
        self.assertEqual(len(updated), 1)
        self.assertEqual(updated[0][0].id, node_id)
        self.assertEqual(old_results, [])

        delete_node(self.conn, node_id)
        self.assertEqual(fts_search(self.conn, "Beta"), [])

    def test_find_by_content_hash_prefers_first_non_archived_node(self) -> None:
        first_id = create_node(self.conn, make_node(title="First", content_hash="hash-1"))
        create_node(self.conn, make_node(title="Second", content_hash="hash-1", status="reference"))
        create_node(self.conn, make_node(title="Archived", content_hash="hash-archived", status="archived"))

        found = find_by_content_hash(self.conn, "hash-1")
        self.assertIsNotNone(found)
        assert found is not None
        self.assertEqual(found.id, first_id)
        self.assertIsNone(find_by_content_hash(self.conn, "hash-archived"))

    def test_edge_weight_is_clamped(self) -> None:
        source_id = create_node(self.conn, make_node(title="Source"))
        target_id = create_node(self.conn, make_node(title="Target", node_type="entity"))
        create_edge(self.conn, make_edge(source_id, target_id, weight=0.95))

        update_edge_weight(self.conn, source_id, target_id, "RELATED", 0.2)
        self.assertEqual(get_edges_from(self.conn, source_id)[0].weight, 1.0)

        update_edge_weight(self.conn, source_id, target_id, "RELATED", -2.0)
        self.assertEqual(get_edges_from(self.conn, source_id)[0].weight, 0.0)

    def test_importance_updates_are_clamped(self) -> None:
        first_id = create_node(self.conn, make_node(title="First"))
        second_id = create_node(self.conn, make_node(title="Second"))

        update_importance(self.conn, first_id, 1.5)
        bulk_update_importance(self.conn, [(second_id, -0.25)])

        self.assertEqual(get_node(self.conn, first_id).importance, 1.0)
        self.assertEqual(get_node(self.conn, second_id).importance, 0.0)

    def test_initialize_is_idempotent(self) -> None:
        initialize(self.conn)
        initialize(self.conn)
        self.assertEqual(get_current_version(self.conn), 2)

    def test_foreign_keys_are_enforced_for_edges(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            create_edge(self.conn, make_edge("missing-source", "missing-target"))


class HealthCheckOnInitTests(unittest.TestCase):
    """O2: get_initialized_connection runs check_database_health once per process per path."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "pam.db"
        schema_module._HEALTH_CHECKED_PATHS.clear()

    def tearDown(self) -> None:
        schema_module._HEALTH_CHECKED_PATHS.clear()
        self._tmp.cleanup()

    def test_runs_health_check_on_first_connection(self) -> None:
        with mock.patch.object(
            schema_module, "check_database_health", wraps=schema_module.check_database_health
        ) as health_mock:
            conn = get_initialized_connection(self.db_path)
        conn.close()
        self.assertEqual(health_mock.call_count, 1)

    def test_skips_health_check_on_subsequent_connections_to_same_path(self) -> None:
        with mock.patch.object(
            schema_module, "check_database_health", wraps=schema_module.check_database_health
        ) as health_mock:
            get_initialized_connection(self.db_path).close()
            get_initialized_connection(self.db_path).close()
            get_initialized_connection(self.db_path).close()
        self.assertEqual(health_mock.call_count, 1)

    def test_runs_health_check_again_for_a_different_path(self) -> None:
        other_path = Path(self._tmp.name) / "other.db"
        with mock.patch.object(
            schema_module, "check_database_health", wraps=schema_module.check_database_health
        ) as health_mock:
            get_initialized_connection(self.db_path).close()
            get_initialized_connection(other_path).close()
        self.assertEqual(health_mock.call_count, 2)

    def test_logs_warning_when_health_check_reports_drift(self) -> None:
        unhealthy = {
            "is_healthy": False,
            "nodes_count": 12,
            "missing_fts_rows": 3,
            "orphaned_fts_rows": 0,
        }
        with mock.patch.object(schema_module, "check_database_health", return_value=unhealthy):
            with self.assertLogs("pam.db.schema", level="WARNING") as captured:
                get_initialized_connection(self.db_path).close()
        self.assertTrue(any("FTS drift detected" in line for line in captured.output))

    def test_silent_when_healthy(self) -> None:
        with mock.patch.object(
            schema_module, "check_database_health", wraps=schema_module.check_database_health
        ):
            logger = logging.getLogger("pam.db.schema")
            old_level = logger.level
            logger.setLevel(logging.WARNING)
            try:
                with self.assertLogs("pam.db.schema", level="WARNING") as captured:
                    get_initialized_connection(self.db_path).close()
                    logger.warning("sentinel")
            finally:
                logger.setLevel(old_level)
        # Only the sentinel should appear; no FTS drift warning.
        self.assertEqual(len(captured.output), 1)
        self.assertIn("sentinel", captured.output[0])


if __name__ == "__main__":
    unittest.main()