"""Tests for the operator-facing health surface: doctor_report + rebuild_fts."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest import mock

from pam.db.fts import rebuild_fts
from pam.db.nodes import Node, create_node
from pam.db.schema import doctor_report, get_connection, initialize


def _node(title: str = "T", content: str = "C", suffix: str = "") -> Node:
    now = datetime.now(timezone.utc)
    return Node(
        id="",
        type="note",
        title=title,
        content=content,
        summary="",
        content_hash=f"{title}-{content}-{suffix}",
        created_at=now,
        valid_at=now,
        updated_at=now,
        tags=[],
        session_id=None,
        importance=0.5,
        access_count=0,
        status="active",
        metadata={},
        workspace_id="ws-test",
    )


class DoctorReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = get_connection(":memory:")
        initialize(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def test_fresh_db_is_healthy(self) -> None:
        report = doctor_report(self.conn)
        self.assertTrue(report["is_healthy"])
        self.assertEqual(report["nodes_count"], 0)
        self.assertEqual(report["missing_fts_rows"], 0)
        self.assertEqual(report["orphaned_fts_rows"], 0)
        self.assertEqual(report["integrity_check"], "ok")
        self.assertTrue(report["integrity_ok"])
        self.assertGreaterEqual(report["schema_version"], 1)

    def test_missing_fts_row_marks_unhealthy(self) -> None:
        create_node(self.conn, _node(title="A"))
        # Force drift: delete the FTS row directly.
        self.conn.execute("DELETE FROM fts_index")
        self.conn.commit()

        report = doctor_report(self.conn)
        self.assertFalse(report["is_healthy"])
        self.assertEqual(report["missing_fts_rows"], 1)

    def test_orphaned_fts_row_marks_unhealthy(self) -> None:
        # Insert an FTS row pointing at a non-existent node.
        self.conn.execute(
            "INSERT INTO fts_index(node_id, title, content, summary) VALUES (?, ?, ?, ?)",
            ("nonexistent-id", "ghost", "", ""),
        )
        self.conn.commit()

        report = doctor_report(self.conn)
        self.assertFalse(report["is_healthy"])
        self.assertEqual(report["orphaned_fts_rows"], 1)

    def test_reports_missing_embeddings(self) -> None:
        # Two nodes created via direct mutator skip the embedding path,
        # so they should show up as missing.
        create_node(self.conn, _node(title="A"))
        create_node(self.conn, _node(title="B"))
        report = doctor_report(self.conn)
        self.assertTrue(report["vec_table_present"])
        self.assertEqual(report["nodes_missing_embeddings"], 2)


class RebuildFtsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = get_connection(":memory:")
        initialize(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def test_rebuild_fixes_missing_rows(self) -> None:
        create_node(self.conn, _node(title="A", content="alpha"))
        create_node(self.conn, _node(title="B", content="beta"))
        self.conn.execute("DELETE FROM fts_index")
        self.conn.commit()
        self.assertFalse(doctor_report(self.conn)["is_healthy"])

        indexed = rebuild_fts(self.conn)
        self.assertEqual(indexed, 2)
        self.assertTrue(doctor_report(self.conn)["is_healthy"])

    def test_rebuild_clears_orphans(self) -> None:
        create_node(self.conn, _node(title="A"))
        self.conn.execute(
            "INSERT INTO fts_index(node_id, title, content, summary) VALUES (?, ?, ?, ?)",
            ("ghost", "ghost-title", "", ""),
        )
        self.conn.commit()
        self.assertFalse(doctor_report(self.conn)["is_healthy"])

        rebuild_fts(self.conn)
        report = doctor_report(self.conn)
        self.assertEqual(report["orphaned_fts_rows"], 0)
        self.assertTrue(report["is_healthy"])


if __name__ == "__main__":
    unittest.main()
