from __future__ import annotations

import struct
import unittest
from datetime import datetime, timezone
from unittest import mock

from pam.db.nodes import Node, create_node
from pam.db.schema import get_connection, initialize
from pam.embeddings import (
    EMBEDDING_DIM,
    EmbeddingsUnavailable,
    backfill_embeddings,
)


def _fake_vec(seed: float = 0.1) -> bytes:
    return struct.pack(f"<{EMBEDDING_DIM}f", *([seed] * EMBEDDING_DIM))


def _node(
    *,
    node_type: str = "note",
    title: str = "Title",
    content: str = "Content",
    summary: str = "Summary",
    metadata: dict | None = None,
) -> Node:
    now = datetime.now(timezone.utc)
    return Node(
        id="",
        type=node_type,
        title=title,
        content=content,
        summary=summary,
        content_hash=f"{title}-{content}-hash",
        created_at=now,
        valid_at=now,
        updated_at=now,
        tags=[],
        session_id=None,
        importance=0.5,
        access_count=0,
        status="active",
        metadata=metadata or {},
        workspace_id="ws-test",
    )


class BackfillEmbeddingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = get_connection(":memory:")
        initialize(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def _vec_map_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM vec_node_map").fetchone()[0]

    def test_raises_when_vec_table_missing(self) -> None:
        self.conn.execute("DROP TABLE vec_node_map")
        with self.assertRaises(EmbeddingsUnavailable):
            backfill_embeddings(self.conn)

    def test_raises_when_model_unavailable(self) -> None:
        with mock.patch("pam.embeddings.is_available", return_value=False):
            with self.assertRaises(EmbeddingsUnavailable):
                backfill_embeddings(self.conn)

    def test_embeds_all_unmapped_nodes(self) -> None:
        ids = [
            create_node(self.conn, _node(title=f"Note {i}", content=f"Body {i}"))
            for i in range(3)
        ]
        with mock.patch("pam.embeddings.is_available", return_value=True), \
             mock.patch("pam.embeddings.embed_text", return_value=_fake_vec()):
            stats = backfill_embeddings(self.conn)
        self.assertEqual(stats.total, 3)
        self.assertEqual(stats.embedded, 3)
        self.assertEqual(stats.skipped_empty_text, 0)
        self.assertEqual(self._vec_map_count(), 3)
        mapped_ids = {
            row["node_id"]
            for row in self.conn.execute("SELECT node_id FROM vec_node_map").fetchall()
        }
        self.assertEqual(mapped_ids, set(ids))

    def test_idempotent_second_run_embeds_zero(self) -> None:
        create_node(self.conn, _node(title="One"))
        create_node(self.conn, _node(title="Two", content="Other"))
        with mock.patch("pam.embeddings.is_available", return_value=True), \
             mock.patch("pam.embeddings.embed_text", return_value=_fake_vec()):
            first = backfill_embeddings(self.conn)
            second = backfill_embeddings(self.conn)
        self.assertEqual(first.embedded, 2)
        self.assertEqual(second.total, 0)
        self.assertEqual(second.embedded, 0)
        self.assertEqual(self._vec_map_count(), 2)

    def test_skips_empty_text_nodes(self) -> None:
        create_node(self.conn, _node(title="", content="", summary=""))
        create_node(self.conn, _node(title="Real"))
        with mock.patch("pam.embeddings.is_available", return_value=True), \
             mock.patch("pam.embeddings.embed_text", return_value=_fake_vec()):
            stats = backfill_embeddings(self.conn)
        self.assertEqual(stats.total, 2)
        self.assertEqual(stats.embedded, 1)
        self.assertEqual(stats.skipped_empty_text, 1)

    def test_entity_text_uses_aliases_and_category(self) -> None:
        create_node(
            self.conn,
            _node(
                node_type="entity",
                title="Anya",
                content="",
                summary="",
                metadata={"aliases": ["Anya", "AK"], "category": "person"},
            ),
        )
        captured: list[str] = []

        def capture(text: str) -> bytes:
            captured.append(text)
            return _fake_vec()

        with mock.patch("pam.embeddings.is_available", return_value=True), \
             mock.patch("pam.embeddings.embed_text", side_effect=capture):
            stats = backfill_embeddings(self.conn)
        self.assertEqual(stats.embedded, 1)
        self.assertEqual(len(captured), 1)
        self.assertIn("Anya", captured[0])
        self.assertIn("AK", captured[0])
        self.assertIn("person", captured[0])


class EntityIngestEmbeddingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = get_connection(":memory:")
        initialize(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def test_new_entity_gets_embedded(self) -> None:
        from pam.ingestion.entity_linker import link_entities_detailed

        parent_id = create_node(
            self.conn,
            _node(title="Parent note", content="Some content"),
        )
        captured: list[str] = []

        def capture(text: str) -> bytes:
            captured.append(text)
            return _fake_vec()

        with mock.patch("pam.embeddings.embed_text", side_effect=capture):
            result = link_entities_detailed(
                self.conn,
                node_id=parent_id,
                entities=[{"name": "Mira", "category": "person"}],
                edge_facts={},
                workspace_id="ws-test",
            )
        self.assertEqual(result.created_new, 1)
        entity_text = next((t for t in captured if "Mira" in t), None)
        self.assertIsNotNone(entity_text, f"expected an embed call for entity, got {captured}")
        self.assertIn("person", entity_text)
        mapped_count = self.conn.execute(
            "SELECT COUNT(*) FROM vec_node_map WHERE node_id IN (SELECT id FROM nodes WHERE type='entity')"
        ).fetchone()[0]
        self.assertEqual(mapped_count, 1)


if __name__ == "__main__":
    unittest.main()
