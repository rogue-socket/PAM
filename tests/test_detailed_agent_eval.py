from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from unittest import TestCase, mock

import pam.db.schema as schema_module
from pam.agent_interface import ingest_for_agent, query_for_agent
from pam.db.schema import check_database_health, get_connection, initialize
from pam.feedback import supersede
from pam.retrieval.query_parser import LLMUnavailableError


DETAILED_EVAL_SCRIPT_PATH = Path(__file__).resolve().parents[1] / ".tmp_manual_cli" / "detailed_memory_eval" / "run_detailed_eval.py"


@lru_cache(maxsize=1)
def load_detailed_eval_fixture() -> dict:
    spec = importlib.util.spec_from_file_location("pam_detailed_eval_fixture", DETAILED_EVAL_SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load detailed evaluation fixture from {DETAILED_EVAL_SCRIPT_PATH}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {
        "corpus": module.CORPUS,
        "queries": module.QUERIES,
        "supersedes": module.SUPERSEDES,
    }


class DetailedAgentEvaluationSuiteTests(TestCase):
    def setUp(self) -> None:
        self.fixture = load_detailed_eval_fixture()
        self.temp_dir = Path(self.id().replace(".", "_"))
        self.db_temp_dir = Path.cwd() / ".tmp_manual_cli" / "test_detailed_agent_eval"
        self.db_temp_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.db_temp_dir / "pam-detailed-agent-eval.db"
        self.log_path = self.db_temp_dir / "pam-detailed-agent-eval.jsonl"

        if self.db_path.exists():
            self.db_path.unlink()
        if self.log_path.exists():
            self.log_path.unlink()

        self.link_dir = self.db_temp_dir / "link_sources"
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
        if self.db_path.exists():
            self.db_path.unlink()
        if self.log_path.exists():
            self.log_path.unlink()
        if self.link_dir.exists():
            for child in self.link_dir.iterdir():
                child.unlink()
            self.link_dir.rmdir()

    def test_fixture_contains_full_detailed_corpus_and_queries(self) -> None:
        corpus = self.fixture["corpus"]
        queries = self.fixture["queries"]

        self.assertEqual(len(corpus), 55)
        self.assertEqual(len(queries), 110)
        self.assertEqual(sum(1 for item in queries if item["kind"] == "direct"), 32)
        self.assertEqual(sum(1 for item in queries if item["kind"] == "indirect"), 78)

    def test_agent_surfaces_support_detailed_natural_language_eval_floor(self) -> None:
        node_ids = self._ingest_full_corpus_via_agent_interface()

        conn = get_connection(self.db_path)
        try:
            health = check_database_health(conn)
        finally:
            conn.close()

        self.assertTrue(health["is_healthy"])
        self.assertEqual(health["nodes_count"], 55)
        self.assertEqual(health["missing_fts_rows"], 0)
        self.assertEqual(health["orphaned_fts_rows"], 0)

        summary = self._evaluate_queries_via_agent_interface()
        miss_preview = "\n".join(
            f"- #{item['index']} [{item['kind']}/{item['query_type']}] {item['query']}"
            for item in summary["misses"][:12]
        )

        self.assertEqual(len(node_ids), 55)
        self.assertEqual(summary["direct_hits"], 32, miss_preview)
        self.assertGreaterEqual(summary["indirect_hits"], 58, miss_preview)
        self.assertGreaterEqual(summary["overall_hits"], 88, miss_preview)
        self.assertGreaterEqual(summary["timeline_hits"], 7, miss_preview)
        self.assertGreaterEqual(summary["relationship_hits"], 19, miss_preview)

    def test_launch_revision_query_surfaces_current_target_and_supersedes_edge(self) -> None:
        self._ingest_full_corpus_via_agent_interface()

        result = query_for_agent("What new public launch date replaced April 18?", top_k=10, workspace_id=Path.cwd())

        note_titles = [node.title for node in result.notes]
        source_titles = [node.title for node in result.sources]
        node_lookup = {node.id: node.title for node in [*result.events, *result.entities, *result.notes, *result.sources]}
        relationship_triples = [
            (node_lookup.get(edge.source_id, edge.source_id), edge.relation, node_lookup.get(edge.target_id, edge.target_id))
            for edge in result.relationships
        ]

        self.assertGreaterEqual(len(note_titles), 2)
        self.assertTrue(note_titles[0].startswith("Idea: revise the public launch target to 2026-04-26"))
        self.assertIn("2026-04-18", note_titles[1])
        self.assertEqual(source_titles[:1], ["Launch checklist"])
        self.assertIn((note_titles[0], "SUPERSEDES", note_titles[1]), relationship_triples)

    def test_cross_discipline_bridge_queries_surface_eval_relationships(self) -> None:
        self._ingest_full_corpus_via_agent_interface()

        source_result = query_for_agent(
            "What source was derived from the cross-discipline orchestration idea?",
            top_k=10,
            workspace_id=Path.cwd(),
        )
        event_result = query_for_agent(
            "Which event linked immune memory, jazz improvisation, and transit headway control?",
            top_k=10,
            workspace_id=Path.cwd(),
        )
        planning_result = query_for_agent(
            "Which source used energy landscapes to explain planning search?",
            top_k=10,
            workspace_id=Path.cwd(),
        )

        source_titles = [node.title for node in source_result.sources]
        event_text = self._flatten_result_text(event_result).lower()
        planning_titles = [node.title for node in planning_result.sources]

        self.assertIn("Cybernetics bridge memo", source_titles)
        self.assertIn("adaptive orchestration", self._flatten_result_text(source_result).lower())
        self.assertIn("cross-discipline roundtable", event_text)
        self.assertIn("adaptive orchestration", event_text)
        self.assertIn("Energy landscape note", planning_titles)

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
                    parent_note_id=parent_note_id,
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
            "direct_hits": 0,
            "indirect_hits": 0,
            "timeline_hits": 0,
            "relationship_hits": 0,
            "misses": [],
        }

        for index, query_case in enumerate(self.fixture["queries"], start=1):
            result = query_for_agent(query_case["query"], top_k=10, workspace_id=Path.cwd())
            all_nodes = [*result.events, *result.entities, *result.notes, *result.sources]

            if query_case.get("expect_empty"):
                passed = all_nodes == []
            else:
                flattened = self._flatten_result_text(result).lower()
                passed = any(expected.lower() in flattened for expected in query_case["expected_substrings"])

            if passed:
                summary["overall_hits"] += 1
                if query_case["kind"] == "direct":
                    summary["direct_hits"] += 1
                else:
                    summary["indirect_hits"] += 1
                if query_case["query_type"] == "timeline":
                    summary["timeline_hits"] += 1
                if query_case["query_type"] == "relationship":
                    summary["relationship_hits"] += 1
                continue

            summary["misses"].append(
                {
                    "index": index,
                    "kind": query_case["kind"],
                    "query_type": query_case["query_type"],
                    "query": query_case["query"],
                    "returned_count": len(all_nodes),
                }
            )

        return summary

    @staticmethod
    def _flatten_result_text(result) -> str:
        chunks: list[str] = []
        for node in [*result.events, *result.entities, *result.notes, *result.sources]:
            chunks.extend([node.title, node.content, node.summary])
        return "\n".join(chunk for chunk in chunks if chunk)

    @staticmethod
    def _relationship_triples(result) -> list[tuple[str, str, str]]:
        node_lookup = {node.id: node.title for node in [*result.events, *result.entities, *result.notes, *result.sources]}
        return [
            (node_lookup.get(edge.source_id, edge.source_id), edge.relation, node_lookup.get(edge.target_id, edge.target_id))
            for edge in result.relationships
        ]