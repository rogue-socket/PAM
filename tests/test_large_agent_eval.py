from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from unittest import TestCase, mock

import pam.db.schema as schema_module
from pam.agent_interface import ingest_for_agent, query_for_agent
from pam.db.schema import check_database_health, get_connection, initialize
from pam.feedback import supersede
from pam.retrieval.query_parser import LLMUnavailableError


LARGE_EVAL_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "large_agent_eval_corpus.json"


@lru_cache(maxsize=1)
def load_large_eval_fixture() -> dict:
    with LARGE_EVAL_FIXTURE_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


class LargeAgentEvaluationSuiteTests(TestCase):
    def setUp(self) -> None:
        self.fixture = load_large_eval_fixture()
        self.temp_dir = tempfile.TemporaryDirectory()
        temp_root = Path(self.temp_dir.name)
        self.db_path = temp_root / "pam-large-agent-eval.db"
        self.log_path = temp_root / "pam-large-agent-eval.jsonl"
        self.link_dir = temp_root / "link_sources"
        self.link_dir.mkdir(parents=True, exist_ok=True)

        self.db_patch = mock.patch.object(schema_module, "DB_PATH", self.db_path)
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)

        self.ingest_log_patch = mock.patch("pam.ingestion.pipeline.LOG_PATH", self.log_path)
        self.ingest_log_patch.start()
        self.addCleanup(self.ingest_log_patch.stop)

        self.query_log_patch = mock.patch("pam.retrieval.search.LOG_PATH", self.log_path)
        self.query_log_patch.start()
        self.addCleanup(self.query_log_patch.stop)

        self.summarize_patch = mock.patch("pam.ingestion.pipeline.summarize", return_value="")
        self.summarize_patch.start()
        self.addCleanup(self.summarize_patch.stop)

        self.entities_patch = mock.patch("pam.ingestion.pipeline.extract_entities", return_value=[])
        self.entities_patch.start()
        self.addCleanup(self.entities_patch.stop)

        self.edge_fact_patch = mock.patch("pam.ingestion.pipeline.generate_edge_fact", return_value="")
        self.edge_fact_patch.start()
        self.addCleanup(self.edge_fact_patch.stop)

        self.query_parser_patch = mock.patch(
            "pam.retrieval.query_parser._invoke_llm",
            side_effect=LLMUnavailableError("missing sdk"),
        )
        self.query_parser_patch.start()
        self.addCleanup(self.query_parser_patch.stop)

        conn = get_connection(self.db_path)
        try:
            initialize(conn)
        finally:
            conn.close()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_fixture_contains_100_corpus_items_and_200_queries(self) -> None:
        corpus = self.fixture["corpus"]
        queries = self.fixture["queries"]

        self.assertEqual(len(corpus), 100)
        self.assertEqual(len(queries), 200)
        self.assertEqual(sum(1 for item in corpus if item["ingest_kind"] == "note"), 40)
        self.assertEqual(sum(1 for item in corpus if item["ingest_kind"] == "file"), 20)
        self.assertEqual(sum(1 for item in corpus if item["ingest_kind"] == "url"), 20)
        self.assertEqual(sum(1 for item in corpus if item["ingest_kind"] == "event"), 20)
        self.assertEqual(sum(1 for item in queries if item["query_type"] == "lookup"), 80)
        self.assertEqual(sum(1 for item in queries if item["query_type"] == "paraphrase"), 40)
        self.assertEqual(sum(1 for item in queries if item["query_type"] == "relationship"), 40)
        self.assertEqual(sum(1 for item in queries if item["query_type"] == "timeline"), 20)
        self.assertEqual(sum(1 for item in queries if item["query_type"] == "negative"), 20)

    def test_agent_surfaces_support_large_natural_language_eval_floor(self) -> None:
        node_ids = self._ingest_full_corpus_via_agent_interface()

        conn = get_connection(self.db_path)
        try:
            health = check_database_health(conn)
        finally:
            conn.close()

        self.assertTrue(health["is_healthy"])
        self.assertEqual(health["nodes_count"], 100)
        self.assertEqual(health["missing_fts_rows"], 0)
        self.assertEqual(health["orphaned_fts_rows"], 0)

        summary = self._evaluate_queries_via_agent_interface()
        miss_preview = "\n".join(
            f"- #{item['index']} [{item['query_type']}] {item['query']}"
            for item in summary["misses"][:15]
        )
        score_line = (
            f"overall={summary['overall_hits']}/{summary['overall_total']} ({summary['overall_score']:.1f}%) | "
            f"lookup={summary['query_type_hits']['lookup']}/{summary['query_type_totals']['lookup']} | "
            f"paraphrase={summary['query_type_hits']['paraphrase']}/{summary['query_type_totals']['paraphrase']} | "
            f"relationship={summary['query_type_hits']['relationship']}/{summary['query_type_totals']['relationship']} | "
            f"timeline={summary['query_type_hits']['timeline']}/{summary['query_type_totals']['timeline']} | "
            f"negative={summary['query_type_hits']['negative']}/{summary['query_type_totals']['negative']}"
        )
        failure_message = f"{score_line}\n{miss_preview}" if miss_preview else score_line

        self.assertEqual(len(node_ids), 100)
        self.assertGreaterEqual(summary["overall_score"], 92.0, failure_message)
        self.assertGreaterEqual(summary["query_type_hits"]["lookup"], 76, failure_message)
        self.assertGreaterEqual(summary["query_type_hits"]["paraphrase"], 36, failure_message)
        self.assertGreaterEqual(summary["query_type_hits"]["relationship"], 34, failure_message)
        self.assertGreaterEqual(summary["query_type_hits"]["timeline"], 16, failure_message)
        self.assertGreaterEqual(summary["query_type_hits"]["negative"], 19, failure_message)

    def test_negative_query_returns_no_nodes_for_out_of_fixture_topic(self) -> None:
        self._ingest_full_corpus_via_agent_interface()

        result = query_for_agent("What do we know about Velvet Comet vacuum orchids?", top_k=10, workspace_id=Path.cwd())

        all_nodes = [*result.events, *result.entities, *result.notes, *result.sources]
        self.assertEqual(all_nodes, [])
        self.assertEqual(result.relationships, [])

    def test_relationship_query_surfaces_expected_derived_source(self) -> None:
        self._ingest_full_corpus_via_agent_interface()

        result = query_for_agent("What source was derived from the revised Aurora Ledger plan?", top_k=10, workspace_id=Path.cwd())

        note_titles = [node.title for node in result.notes]
        source_titles = [node.title for node in result.sources]
        node_lookup = {node.id: node.title for node in [*result.events, *result.entities, *result.notes, *result.sources]}
        relationship_triples = [
            (node_lookup.get(edge.source_id, edge.source_id), edge.relation, node_lookup.get(edge.target_id, edge.target_id))
            for edge in result.relationships
        ]

        self.assertGreaterEqual(len(note_titles), 1)
        self.assertTrue(note_titles[0].startswith("Idea: revise Aurora Ledger target to 2026-05-26"))
        self.assertIn("Aurora Ledger rollout brief", source_titles)
        self.assertIn((note_titles[0], "DERIVED_FROM", "Aurora Ledger rollout brief"), relationship_triples)

    def _ingest_full_corpus_via_agent_interface(self) -> dict[str, str]:
        node_ids: dict[str, str] = {}

        for item in self.fixture["corpus"]:
            valid_at = datetime.fromisoformat(item["at"]).replace(tzinfo=timezone.utc)
            parent_note_id = None
            if item.get("derived_from"):
                parent_note_id = node_ids[item["derived_from"]]

            if item["ingest_kind"] == "url":
                source_path = self.link_dir / item["filename"]
                source_path.write_text(item["text"], encoding="utf-8")
                result = ingest_for_agent(
                    source_path.resolve().as_uri(),
                    session_id=item["session"],
                    valid_at=valid_at,
                    workspace_id=Path.cwd(),
                )
            elif item["ingest_kind"] == "file":
                result = ingest_for_agent(
                    item["text"],
                    kind="source",
                    session_id=item["session"],
                    valid_at=valid_at,
                    workspace_id=Path.cwd(),
                    parent_note_id=parent_note_id,
                )
            elif item["ingest_kind"] == "event":
                result = ingest_for_agent(
                    item["text"],
                    kind="event",
                    session_id=item["session"],
                    valid_at=valid_at,
                    workspace_id=Path.cwd(),
                )
            else:
                result = ingest_for_agent(
                    item["text"],
                    kind="note",
                    session_id=item["session"],
                    valid_at=valid_at,
                    workspace_id=Path.cwd(),
                )

            node_ids[item["key"]] = result.node_id

        conn = get_connection(self.db_path)
        try:
            for old_key, new_key in self.fixture["supersedes"]:
                self.assertTrue(supersede(conn, node_ids[new_key], node_ids[old_key]))
        finally:
            conn.close()

        return node_ids

    def _evaluate_queries_via_agent_interface(self) -> dict:
        summary = {
            "overall_hits": 0,
            "overall_total": len(self.fixture["queries"]),
            "overall_score": 0.0,
            "query_type_hits": {"lookup": 0, "paraphrase": 0, "relationship": 0, "timeline": 0, "negative": 0},
            "query_type_totals": {"lookup": 0, "paraphrase": 0, "relationship": 0, "timeline": 0, "negative": 0},
            "misses": [],
        }

        for index, query_case in enumerate(self.fixture["queries"], start=1):
            query_type = query_case["query_type"]
            summary["query_type_totals"][query_type] += 1

            result = query_for_agent(query_case["query"], top_k=10, workspace_id=Path.cwd())
            all_nodes = [*result.events, *result.entities, *result.notes, *result.sources]

            if query_case.get("expect_empty"):
                passed = all_nodes == []
            else:
                flattened = self._flatten_result_text(result).lower()
                passed = any(expected in flattened for expected in query_case["expected_substrings"])

            if passed:
                summary["overall_hits"] += 1
                summary["query_type_hits"][query_type] += 1
                continue

            summary["misses"].append(
                {
                    "index": index,
                    "query_type": query_type,
                    "query": query_case["query"],
                    "returned_count": len(all_nodes),
                }
            )

        summary["overall_score"] = summary["overall_hits"] / summary["overall_total"] * 100.0
        return summary

    @staticmethod
    def _flatten_result_text(result) -> str:
        chunks: list[str] = []
        for node in [*result.events, *result.entities, *result.notes, *result.sources]:
            chunks.extend([node.title, node.content, node.summary])
        return "\n".join(chunk for chunk in chunks if chunk)