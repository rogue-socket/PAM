"""Failure-injection tests for ingest's transaction boundary.

A mock raises mid-pipeline; assert that the partial main_node /
entities / edges were rolled back, so the DB is back to its
pre-ingest state.
"""
from __future__ import annotations

import unittest
from unittest import mock

from pam.db.nodes import list_nodes
from pam.db.schema import get_connection, initialize
from pam.ingestion.pipeline import ingest


def _ingest(conn, text: str) -> str | None:
    try:
        return ingest(text, "note", conn=conn)
    except RuntimeError:
        return None


class IngestAtomicityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = get_connection(":memory:")
        initialize(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def test_failure_after_main_node_rolls_back(self) -> None:
        # Mock the embed step (runs right after create_node) to raise.
        with mock.patch(
            "pam.ingestion.pipeline._embed_node",
            side_effect=RuntimeError("boom-after-create"),
        ):
            with self.assertRaises(RuntimeError):
                ingest("Some content for an ingest test", "note", conn=self.conn)

        nodes = list_nodes(self.conn)
        self.assertEqual(
            len(nodes), 0,
            f"main node should have been rolled back; got {[(n.id, n.title) for n in nodes]}",
        )

    def test_failure_in_link_entities_rolls_back_main_and_entities(self) -> None:
        # First, force entity extraction to return something.
        # Then, fail inside link_entities_detailed (after some entity nodes are created).
        fake_entities = [
            {"name": "Anya", "category": "person"},
            {"name": "Auth", "category": "project"},
        ]
        with mock.patch(
            "pam.ingestion.pipeline._run_llm_enrichment",
            return_value=("summary text", fake_entities, {}, 1),
        ), mock.patch(
            # Fail on the third create_edge in entity_linker, AFTER at least
            # one entity has been created. The transaction must roll back
            # the main node, both entity nodes, and any REFERS_TO edges.
            "pam.ingestion.entity_linker.create_edge",
            side_effect=RuntimeError("boom-in-link"),
        ):
            with self.assertRaises(RuntimeError):
                ingest("Content mentions Anya and Auth project", "note", conn=self.conn)

        nodes = list_nodes(self.conn)
        entity_nodes = [n for n in nodes if n.type == "entity"]
        note_nodes = [n for n in nodes if n.type == "note"]
        self.assertEqual(len(note_nodes), 0, f"main note should be rolled back; got {note_nodes}")
        self.assertEqual(len(entity_nodes), 0, f"entity nodes should be rolled back; got {entity_nodes}")

    def test_successful_ingest_persists(self) -> None:
        # Sanity check — the transaction wrap shouldn't break the happy path.
        node_id = ingest("Plain successful ingest", "note", conn=self.conn)
        self.assertTrue(node_id)
        nodes = list_nodes(self.conn)
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0].id, node_id)


if __name__ == "__main__":
    unittest.main()
