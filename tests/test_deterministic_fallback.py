"""Contract test: PAM must function with no LLM available.

The architecture document treats deterministic fallback as a hard
requirement. This test enforces it from the outside: with every LLM call
short-circuited to LLMUnavailableError, ingest must still create nodes,
query parsing must still produce a usable ParsedQuery, and retrieval must
still return sensible non-empty results.

If a future change makes any of ingest / query parsing depend on a
working LLM, this test will fail.
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest import mock

import pam.db.schema as schema_module
from pam.db.nodes import get_node
from pam.db.schema import get_connection, initialize
from pam.ingestion.llm import LLMUnavailableError
from pam.ingestion.pipeline import ingest
from pam.retrieval.query_parser import parse_query_with_metadata
from pam.retrieval.search import retrieve


def _raise_llm_unavailable(*_args, **_kwargs):
    raise LLMUnavailableError("offline contract test: LLM is forced unavailable")


class DeterministicFallbackContractTests(unittest.TestCase):
    """Ingest + retrieve must work with all LLM helpers disabled."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "pam-fallback.db"
        self.log_path = Path(self.temp_dir.name) / "pam-fallback.jsonl"

        self.db_patch = mock.patch.object(schema_module, "DB_PATH", self.db_path)
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)

        self.ingest_log_patch = mock.patch("pam.ingestion.pipeline.LOG_PATH", self.log_path)
        self.ingest_log_patch.start()
        self.addCleanup(self.ingest_log_patch.stop)

        self.query_log_patch = mock.patch("pam.retrieval.search.LOG_PATH", self.log_path)
        self.query_log_patch.start()
        self.addCleanup(self.query_log_patch.stop)

        # Force LLM unavailability everywhere a remote provider would be touched.
        self.ingest_llm_patch = mock.patch(
            "pam.ingestion.llm._call_llm", side_effect=_raise_llm_unavailable
        )
        self.ingest_llm_patch.start()
        self.addCleanup(self.ingest_llm_patch.stop)

        self.query_llm_patch = mock.patch(
            "pam.retrieval.query_parser._invoke_llm", side_effect=_raise_llm_unavailable
        )
        self.query_llm_patch.start()
        self.addCleanup(self.query_llm_patch.stop)

        # Pin the "Neither" tier of the fallback table — no LLM and no
        # embeddings — so this contract test continues to prove FTS+graph
        # correctness when both optional channels are unavailable.
        self.embed_text_patch = mock.patch(
            "pam.embeddings.embed_text", return_value=None
        )
        self.embed_text_patch.start()
        self.addCleanup(self.embed_text_patch.stop)
        self.embed_query_patch = mock.patch(
            "pam.retrieval.search.embed_query", return_value=None
        )
        self.embed_query_patch.start()
        self.addCleanup(self.embed_query_patch.stop)

        conn = get_connection(self.db_path)
        try:
            initialize(conn)
        finally:
            conn.close()

        self.workspace_id = str(Path(self.temp_dir.name).resolve())

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_ingest_creates_node_without_summary_or_entities_when_llm_unavailable(self) -> None:
        node_id = ingest(
            raw_text="Project Aurora launches 2026-09-14 at the Zephyr Harbor dock.",
            input_type="note",
            session_id="offline-1",
            provided_at=datetime(2026, 4, 24, tzinfo=timezone.utc),
            workspace_id=self.workspace_id,
        )

        self.assertTrue(node_id)

        conn = get_connection(self.db_path)
        try:
            stored = get_node(conn, node_id)
        finally:
            conn.close()

        self.assertIsNotNone(stored)
        # Title heuristic still extracted; full text preserved as content.
        self.assertIn("Aurora", stored.content)
        # Summary degrades to empty when summarize() can't reach an LLM.
        self.assertEqual(stored.summary, "")

    def test_query_parser_uses_deterministic_path_when_llm_unavailable(self) -> None:
        parsed, fallback_used = parse_query_with_metadata(
            "When does Project Aurora launch?",
            today=date(2026, 4, 24),
        )

        self.assertTrue(fallback_used, "Expected query parser to fall back when _invoke_llm raises")
        self.assertIsNotNone(parsed)
        # Heuristic keyword extraction must produce something useful.
        keyword_blob = " ".join(parsed.keywords).lower()
        self.assertIn("aurora", keyword_blob)

    def test_retrieve_finds_ingested_node_in_offline_mode(self) -> None:
        ingest(
            raw_text="Project Aurora launches 2026-09-14 at the Zephyr Harbor dock.",
            input_type="note",
            session_id="offline-1",
            provided_at=datetime(2026, 4, 24, tzinfo=timezone.utc),
            workspace_id=self.workspace_id,
        )
        ingest(
            raw_text="Velvet orchard ladders are unrelated and should not collide.",
            input_type="note",
            session_id="offline-1",
            provided_at=datetime(2026, 4, 24, tzinfo=timezone.utc),
            workspace_id=self.workspace_id,
        )

        result = retrieve("Project Aurora launch", workspace_id=self.workspace_id)
        all_nodes = [*result.events, *result.notes, *result.sources, *result.entities]

        self.assertTrue(all_nodes, "FTS must return at least one match without an LLM")
        flattened = " ".join(node.content for node in all_nodes).lower()
        self.assertIn("aurora", flattened)

    def test_unrelated_query_returns_empty_or_unrelated_set(self) -> None:
        ingest(
            raw_text="Project Aurora launches 2026-09-14.",
            input_type="note",
            session_id="offline-1",
            provided_at=datetime(2026, 4, 24, tzinfo=timezone.utc),
            workspace_id=self.workspace_id,
        )

        result = retrieve("velvet orchard ladders", workspace_id=self.workspace_id)
        all_nodes = [*result.events, *result.notes, *result.sources, *result.entities]
        flattened = " ".join(node.content for node in all_nodes).lower()
        self.assertNotIn("aurora", flattened)


if __name__ == "__main__":
    unittest.main()
