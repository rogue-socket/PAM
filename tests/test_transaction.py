from __future__ import annotations

import sqlite3
import unittest
from datetime import datetime, timezone

from pam.db import transaction
from pam.db.edges import Edge, create_edge
from pam.db.nodes import Node, create_node, get_node, list_nodes
from pam.db.schema import get_connection, initialize


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


class TransactionHelperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = get_connection(":memory:")
        initialize(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def test_commit_on_success(self) -> None:
        with transaction(self.conn):
            create_node(self.conn, _node(title="A"), commit=False)
            create_node(self.conn, _node(title="B"), commit=False)
        self.assertEqual(len(list_nodes(self.conn)), 2)

    def test_rollback_on_exception(self) -> None:
        with self.assertRaises(RuntimeError):
            with transaction(self.conn):
                create_node(self.conn, _node(title="A"), commit=False)
                raise RuntimeError("boom")
        self.assertEqual(len(list_nodes(self.conn)), 0)

    def test_nested_savepoint_rolls_back_inner_only(self) -> None:
        with transaction(self.conn):
            outer_id = create_node(self.conn, _node(title="outer"), commit=False)
            try:
                with transaction(self.conn):
                    create_node(self.conn, _node(title="inner"), commit=False)
                    raise RuntimeError("inner boom")
            except RuntimeError:
                pass
            # Outer write survives
        nodes = list_nodes(self.conn)
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0].id, outer_id)

    def test_nested_savepoint_commits_both_on_success(self) -> None:
        with transaction(self.conn):
            create_node(self.conn, _node(title="outer"), commit=False)
            with transaction(self.conn):
                create_node(self.conn, _node(title="inner"), commit=False)
        self.assertEqual(len(list_nodes(self.conn)), 2)

    def test_create_edge_duplicate_inside_txn_does_not_pollute_outer(self) -> None:
        with transaction(self.conn):
            src = create_node(self.conn, _node(title="src"), commit=False)
            tgt = create_node(self.conn, _node(title="tgt"), commit=False)
            edge = Edge(
                source_id=src,
                target_id=tgt,
                relation="RELATED",
                weight=1.0,
                fact="",
                created_at=datetime.now(timezone.utc),
            )
            first = create_edge(self.conn, edge, commit=False)
            second = create_edge(self.conn, edge, commit=False)
            self.assertTrue(first)
            self.assertFalse(second)
            # Outer transaction should still survive the duplicate
            create_node(self.conn, _node(title="after-dup"), commit=False)
        self.assertEqual(len(list_nodes(self.conn)), 3)

    def test_failure_after_partial_writes_rolls_back_all(self) -> None:
        with self.assertRaises(RuntimeError):
            with transaction(self.conn):
                create_node(self.conn, _node(title="one"), commit=False)
                create_node(self.conn, _node(title="two"), commit=False)
                create_node(self.conn, _node(title="three"), commit=False)
                raise RuntimeError("third-stage failure")
        self.assertEqual(len(list_nodes(self.conn)), 0)


if __name__ == "__main__":
    unittest.main()
