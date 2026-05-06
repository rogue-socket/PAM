from __future__ import annotations

import json
import math
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from pam.db.edges import Edge, create_edge, get_edges_from
from pam.db.nodes import Node, create_node, get_node
from pam.db.schema import MIGRATIONS, get_connection, get_current_version, get_initialized_connection, initialize, resolve_workspace_id
from pam.ingestion.pipeline import ingest
from pam.retrieval.graph_expander import expand
from pam.retrieval.query_parser import LLMUnavailableError, ParsedQuery, parse_query, parse_query_with_metadata
from pam.retrieval.ranker import ExpandedResult, rank_and_assemble, score
from pam.retrieval.search import fts_search_with_filter, retrieve


REGRESSION_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "retrieval_regression_corpus.json"


def load_retrieval_regression_corpus() -> dict:
    with REGRESSION_FIXTURE_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


class QueryParserTests(unittest.TestCase):
    def test_parse_query_uses_llm_payload_when_valid(self) -> None:
        llm_response = (
            '{"keywords": ["python", "memory"], '
            '"entities": ["Python"], '
            '"time_range": {"start": "2026-04-01T00:00:00Z", "end": null}, '
            '"intent": "timeline"}'
        )

        with mock.patch("pam.retrieval.query_parser._invoke_llm", return_value=llm_response):
            parsed = parse_query("What did I do with Python?", today=date(2026, 4, 22))

        self.assertEqual(
            parsed,
            ParsedQuery(
                keywords=["python", "memory"],
                entities=["Python"],
                time_range={"start": "2026-04-01T00:00:00Z", "end": None},
                intent="timeline",
                relation_filters=[],
                relation_direction=None,
                answer_mode="node",
                question_shape="lookup",
                anchor_terms=["Python"],
            ),
        )

    def test_parse_query_falls_back_when_llm_raises(self) -> None:
        with mock.patch("pam.retrieval.query_parser._invoke_llm", side_effect=RuntimeError("boom")):
            parsed = parse_query("What did I do about PAM retrieval?", today=date(2026, 4, 22))

        self.assertEqual(parsed.intent, "lookup")
        self.assertEqual(parsed.entities, [])
        self.assertIsNone(parsed.time_range)
        self.assertEqual(parsed.keywords, ["pam", "retrieval"])
        self.assertEqual(parsed.relation_filters, [])
        self.assertEqual(parsed.answer_mode, "node")

    def test_parse_query_falls_back_when_llm_returns_invalid_json(self) -> None:
        with mock.patch("pam.retrieval.query_parser._invoke_llm", return_value="not-json"):
            parsed = parse_query("Where is the pipeline status?", today=date(2026, 4, 22))

        self.assertEqual(parsed.intent, "lookup")
        self.assertEqual(parsed.keywords, ["pipeline", "status"])

    def test_parse_query_fallback_infers_relationship_query_fields(self) -> None:
        with mock.patch("pam.retrieval.query_parser._invoke_llm", side_effect=LLMUnavailableError("missing sdk")):
            parsed = parse_query("What replaced the old launch target?", today=date(2026, 4, 22))

        self.assertEqual(parsed.relation_filters, ["SUPERSEDES"])
        self.assertEqual(parsed.relation_direction, "incoming")
        self.assertEqual(parsed.answer_mode, "relationship")
        self.assertEqual(parsed.question_shape, "evolution")

    def test_parse_query_fallback_infers_outgoing_derived_from_query_fields(self) -> None:
        with mock.patch("pam.retrieval.query_parser._invoke_llm", side_effect=LLMUnavailableError("missing sdk")):
            parsed = parse_query("What source was derived from the revised launch target?", today=date(2026, 4, 22))

        self.assertEqual(parsed.relation_filters, ["DERIVED_FROM"])
        self.assertEqual(parsed.relation_direction, "outgoing")
        self.assertEqual(parsed.answer_mode, "relationship")

    def test_parse_query_fallback_infers_incoming_supersedes_from_superseded_phrase(self) -> None:
        with mock.patch("pam.retrieval.query_parser._invoke_llm", side_effect=LLMUnavailableError("missing sdk")):
            parsed = parse_query("What launch correction superseded the April 18 plan?", today=date(2026, 4, 22))

        self.assertEqual(parsed.relation_filters, ["SUPERSEDES"])
        self.assertEqual(parsed.relation_direction, "incoming")
        self.assertEqual(parsed.answer_mode, "relationship")

    def test_parse_query_fallback_infers_outgoing_supersedes_from_replaced_by_phrase(self) -> None:
        with mock.patch("pam.retrieval.query_parser._invoke_llm", side_effect=LLMUnavailableError("missing sdk")):
            parsed = parse_query("What older launch plan was explicitly replaced by a newer note?", today=date(2026, 4, 22))

        self.assertEqual(parsed.relation_filters, ["SUPERSEDES"])
        self.assertEqual(parsed.relation_direction, "outgoing")
        self.assertEqual(parsed.answer_mode, "relationship")

    def test_parse_query_fallback_infers_contradiction_relation_from_contradictory_phrase(self) -> None:
        with mock.patch("pam.retrieval.query_parser._invoke_llm", side_effect=LLMUnavailableError("missing sdk")):
            parsed = parse_query(
                "What should happen to contradictory ship notices instead of overwriting them?",
                today=date(2026, 4, 22),
            )

        self.assertEqual(parsed.relation_filters, ["CONTRADICTS"])
        self.assertEqual(parsed.relation_direction, "both")
        self.assertEqual(parsed.answer_mode, "relationship")

    def test_parse_query_fallback_marks_generic_relation_prompt_without_forcing_relation_family(self) -> None:
        with mock.patch("pam.retrieval.query_parser._invoke_llm", side_effect=LLMUnavailableError("missing sdk")):
            parsed = parse_query(
                "Which person shows up in both launch planning and the public demo plan?",
                today=date(2026, 4, 22),
            )

        self.assertEqual(parsed.relation_filters, [])
        self.assertIsNone(parsed.relation_direction)
        self.assertEqual(parsed.answer_mode, "relationship")
        self.assertEqual(parsed.question_shape, "relationship")

    def test_parse_query_fallback_infers_theme_query_shape_and_related_expansion(self) -> None:
        with mock.patch("pam.retrieval.query_parser._invoke_llm", side_effect=LLMUnavailableError("missing sdk")):
            parsed = parse_query("What themes are central in the launch planning work?", today=date(2026, 4, 22))

        self.assertEqual(parsed.relation_filters, ["RELATED"])
        self.assertEqual(parsed.answer_mode, "relationship")
        self.assertEqual(parsed.intent, "reason")
        self.assertEqual(parsed.question_shape, "theme")

    def test_parse_query_fallback_infers_gap_query_shape_and_related_expansion(self) -> None:
        with mock.patch("pam.retrieval.query_parser._invoke_llm", side_effect=LLMUnavailableError("missing sdk")):
            parsed = parse_query("What nearby topics have I not explored around launch planning?", today=date(2026, 4, 22))

        self.assertEqual(parsed.relation_filters, ["RELATED"])
        self.assertEqual(parsed.answer_mode, "relationship")
        self.assertEqual(parsed.intent, "reason")
        self.assertEqual(parsed.question_shape, "gap")

    def test_parse_query_silently_falls_back_when_llm_is_unavailable(self) -> None:
        with mock.patch("pam.retrieval.query_parser._invoke_llm", side_effect=LLMUnavailableError("missing sdk")), mock.patch(
            "pam.retrieval.query_parser.logger.warning"
        ) as warning_mock:
            parsed, fallback_used = parse_query_with_metadata("What changed in PAM retrieval?", today=date(2026, 4, 22))

        self.assertTrue(fallback_used)
        self.assertEqual(parsed.keywords, ["changed", "pam", "retrieval"])
        self.assertEqual(parsed.relation_filters, [])
        warning_mock.assert_not_called()

    def test_parse_query_defaults_invalid_intent_to_lookup(self) -> None:
        llm_response = (
            '{"keywords": ["lifecycle"], '
            '"entities": [], '
            '"time_range": null, '
            '"intent": "dance"}'
        )

        with mock.patch("pam.retrieval.query_parser._invoke_llm", return_value=llm_response):
            parsed = parse_query("Tell me about lifecycle", today=date(2026, 4, 22))

        self.assertEqual(parsed.intent, "lookup")
        self.assertEqual(parsed.keywords, ["lifecycle"])

    def test_parse_query_splits_internal_punctuation_in_fallback_keywords(self) -> None:
        with mock.patch("pam.retrieval.query_parser._invoke_llm", side_effect=RuntimeError("boom")):
            parsed = parse_query("What changed on example.com retrieval docs?", today=date(2026, 4, 22))

        self.assertIn("example", parsed.keywords)
        self.assertIn("com", parsed.keywords)
        self.assertNotIn("example.com", parsed.keywords)

    def test_parse_query_fallback_extracts_single_day_time_range(self) -> None:
        with mock.patch("pam.retrieval.query_parser._invoke_llm", side_effect=RuntimeError("boom")):
            parsed = parse_query("What changed on 2026-04-20 retrieval docs?", today=date(2026, 4, 22))

        self.assertEqual(parsed.intent, "timeline")
        self.assertEqual(
            parsed.time_range,
            {
                "start": "2026-04-20T00:00:00Z",
                "end": "2026-04-20T23:59:59.999999Z",
            },
        )
        self.assertEqual(parsed.keywords, ["changed", "retrieval", "docs"])

    def test_parse_query_fallback_extracts_yesterday_time_range(self) -> None:
        with mock.patch("pam.retrieval.query_parser._invoke_llm", side_effect=RuntimeError("boom")):
            parsed = parse_query("What changed yesterday in retrieval?", today=date(2026, 4, 22))

        self.assertEqual(parsed.intent, "timeline")
        self.assertEqual(
            parsed.time_range,
            {
                "start": "2026-04-21T00:00:00Z",
                "end": "2026-04-21T23:59:59.999999Z",
            },
        )
        self.assertEqual(parsed.keywords, ["changed", "yesterday", "retrieval"])

    def test_parse_query_fallback_extracts_since_date_range(self) -> None:
        with mock.patch("pam.retrieval.query_parser._invoke_llm", side_effect=RuntimeError("boom")):
            parsed = parse_query("Show retrieval notes since 2026-04-01", today=date(2026, 4, 22))

        self.assertEqual(parsed.intent, "timeline")
        self.assertEqual(
            parsed.time_range,
            {
                "start": "2026-04-01T00:00:00Z",
                "end": None,
            },
        )
        self.assertEqual(parsed.keywords, ["show", "retrieval", "notes", "since"])


if __name__ == "__main__":
    unittest.main()


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
    workspace_id: str | None = None,
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
        workspace_id=workspace_id,
    )


def make_edge(
    source_id: str,
    target_id: str,
    relation: str,
    *,
    weight: float = 1.0,
    fact: str = "",
) -> Edge:
    return Edge(
        source_id=source_id,
        target_id=target_id,
        relation=relation,
        weight=weight,
        fact=fact,
        created_at=datetime.now(timezone.utc),
    )


class RetrievalModuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "pam-test.db"
        self.log_path = Path(self.temp_dir.name) / "pam_log.jsonl"
        self.conn = get_connection(self.db_path)
        initialize(self.conn)

    def tearDown(self) -> None:
        self.conn.close()
        self.temp_dir.cleanup()

    def _ingest_regression_corpus(self) -> dict:
        corpus = load_retrieval_regression_corpus()
        session_id = "retrieval-regression-session"

        with mock.patch("pam.ingestion.pipeline.LOG_PATH", self.log_path), mock.patch(
            "pam.ingestion.pipeline.summarize", return_value=""
        ), mock.patch("pam.ingestion.pipeline.extract_entities", return_value=[]), mock.patch(
            "pam.ingestion.pipeline.generate_edge_fact", return_value=""
        ):
            for article in corpus["articles"]:
                ingest(article["content"], input_type="document", session_id=session_id, conn=self.conn)

            for note in corpus["notes"]:
                ingest(note, input_type="note", session_id=session_id, node_type="note", conn=self.conn)

            for thought in corpus["thoughts"]:
                ingest(thought, input_type="note", session_id=session_id, node_type="note", conn=self.conn)

        return corpus

    def _retrieve_with_fallback(self, query: str):
        with mock.patch(
            "pam.retrieval.query_parser._invoke_llm",
            side_effect=LLMUnavailableError("missing sdk"),
        ), mock.patch(
            "pam.retrieval.search.get_initialized_connection",
            side_effect=lambda: get_initialized_connection(self.db_path),
        ), mock.patch("pam.retrieval.search.LOG_PATH", self.log_path):
            return retrieve(query, top_k=5)

    @staticmethod
    def _flatten_result_text(result) -> str:
        chunks: list[str] = []
        for node in [*result.events, *result.entities, *result.notes, *result.sources]:
            chunks.extend([node.title, node.content, node.summary])
        return "\n".join(chunk for chunk in chunks if chunk)

    def test_fts_search_falls_back_to_time_range_when_keywords_have_no_recall(self) -> None:
        """Timeline queries with only stop-words ("what did I do last week?") used to
        return zero candidates because FTS-led retrieval requires keyword overlap.
        With the time-range fallback, all in-range nodes surface."""
        in_range_id = create_node(
            self.conn,
            make_node(
                title="Mentoring 1:1 with Diego",
                content="paired on a real bug",
                valid_at=datetime(2026, 4, 29, 14, 0, tzinfo=timezone.utc),
            ),
        )
        out_of_range_id = create_node(
            self.conn,
            make_node(
                title="Older note",
                content="this is older than the window",
                valid_at=datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc),
            ),
        )
        archived_in_range_id = create_node(
            self.conn,
            make_node(
                title="Archived but in range",
                content="should be excluded",
                valid_at=datetime(2026, 4, 30, 12, 0, tzinfo=timezone.utc),
                status="archived",
            ),
        )

        parsed = ParsedQuery(
            keywords=[],
            entities=[],
            time_range={"start": "2026-04-27T00:00:00+00:00", "end": "2026-05-04T23:59:59+00:00"},
            intent="timeline",
        )
        results = fts_search_with_filter(self.conn, parsed, workspace_id=resolve_workspace_id())
        result_ids = [node.id for node, _ in results]

        self.assertIn(in_range_id, result_ids)
        self.assertNotIn(out_of_range_id, result_ids)
        self.assertNotIn(archived_in_range_id, result_ids)

    def test_fts_search_time_range_fallback_skipped_when_no_time_range(self) -> None:
        """Without a time_range, no fallback; empty result is correct."""
        create_node(self.conn, make_node(title="Whatever", content="something"))
        parsed = ParsedQuery(
            keywords=["nonexistent_token_xyz"],
            entities=[],
            time_range=None,
            intent="timeline",
        )
        results = fts_search_with_filter(self.conn, parsed, workspace_id=resolve_workspace_id())
        self.assertEqual(results, [])

    def test_fts_search_returns_matching_node(self) -> None:
        matching_id = create_node(self.conn, make_node(title="Alpha retrieval", content="pipeline", summary="fts"))
        create_node(self.conn, make_node(title="Beta unrelated", content="other", summary="none"))

        parsed = ParsedQuery(keywords=["Alpha"], entities=[], time_range=None, intent="lookup")
        results = fts_search_with_filter(self.conn, parsed, workspace_id=resolve_workspace_id())

        self.assertEqual([node.id for node, _ in results], [matching_id])

    def test_fts_search_handles_punctuated_keywords(self) -> None:
        matching_id = create_node(
            self.conn,
            make_node(
                node_type="source",
                title="example.com docs",
                content="Reference page for PAM retrieval",
                metadata={"url": "https://example.com/docs"},
            ),
        )

        parsed = ParsedQuery(keywords=["example.com"], entities=[], time_range=None, intent="lookup")
        results = fts_search_with_filter(self.conn, parsed, workspace_id=resolve_workspace_id())

        self.assertEqual([node.id for node, _ in results], [matching_id])

    def test_fts_search_seeds_anchor_matches_when_keywords_do_not_recall_them(self) -> None:
        matching_id = create_node(
            self.conn,
            make_node(
                title="Orbit migration plan",
                content="Cutover notes for the rollout",
                summary="anchor-seeded match",
            ),
        )
        create_node(self.conn, make_node(title="Generic rollout memo", content="cutover details"))

        parsed = ParsedQuery(
            keywords=["adjacent"],
            entities=[],
            time_range=None,
            intent="reason",
            anchor_terms=["Orbit"],
        )
        results = fts_search_with_filter(self.conn, parsed, workspace_id=resolve_workspace_id())

        self.assertEqual([node.id for node, _ in results], [matching_id])

    def test_fts_search_applies_valid_at_time_filter(self) -> None:
        old_dt = datetime(2026, 4, 1, tzinfo=timezone.utc)
        new_dt = datetime(2026, 4, 20, tzinfo=timezone.utc)
        create_node(self.conn, make_node(title="Alpha early", content="timeline", valid_at=old_dt))
        recent_id = create_node(self.conn, make_node(title="Alpha recent", content="timeline", valid_at=new_dt))

        parsed = ParsedQuery(
            keywords=["Alpha"],
            entities=[],
            time_range={"start": "2026-04-10T00:00:00Z", "end": "2026-04-25T00:00:00Z"},
            intent="timeline",
        )
        results = fts_search_with_filter(self.conn, parsed, workspace_id=resolve_workspace_id())

        self.assertEqual([node.id for node, _ in results], [recent_id])

    def test_entity_boost_marks_candidate_with_matching_entity(self) -> None:
        note_id = create_node(self.conn, make_node(title="Python note", content="typing", node_type="note"))
        entity_id = create_node(self.conn, make_node(title="Python", node_type="entity"))
        create_edge(self.conn, make_edge(note_id, entity_id, "REFERS_TO", fact="note mentions Python"))

        candidate = get_node(self.conn, note_id)
        assert candidate is not None

        expanded = expand(
            self.conn,
            [candidate],
            ParsedQuery(keywords=["python"], entities=["Python"], time_range=None, intent="lookup"),
        )

        self.assertIn(note_id, expanded.entity_boosted_ids)
        self.assertEqual(expanded.edge_facts[(note_id, entity_id)], "note mentions Python")

    def test_graph_expansion_refers_to_path_adds_entity_and_related_node(self) -> None:
        event_id = create_node(self.conn, make_node(title="Worked on parser", node_type="event"))
        entity_id = create_node(self.conn, make_node(title="PAM", node_type="entity"))
        note_id = create_node(self.conn, make_node(title="Retrieval note", node_type="note"))
        create_edge(self.conn, make_edge(event_id, entity_id, "REFERS_TO"))
        create_edge(self.conn, make_edge(note_id, entity_id, "REFERS_TO"))

        candidate = get_node(self.conn, event_id)
        assert candidate is not None

        expanded = expand(
            self.conn,
            [candidate],
            ParsedQuery(keywords=["parser"], entities=["PAM"], time_range=None, intent="lookup"),
        )

        self.assertEqual({node.id for node in expanded.nodes}, {entity_id, note_id})

    def test_graph_expansion_adds_derived_sources_and_superseded_notes(self) -> None:
        new_note_id = create_node(self.conn, make_node(title="New note", node_type="note"))
        old_note_id = create_node(self.conn, make_node(title="Old note", node_type="note", status="reference"))
        source_id = create_node(self.conn, make_node(title="Meeting transcript", node_type="source"))
        create_edge(self.conn, make_edge(new_note_id, source_id, "DERIVED_FROM", fact="derived from transcript"))
        create_edge(self.conn, make_edge(new_note_id, old_note_id, "SUPERSEDES", fact="replaced older note"))

        candidate = get_node(self.conn, new_note_id)
        assert candidate is not None

        expanded = expand(
            self.conn,
            [candidate],
            ParsedQuery(keywords=["note"], entities=[], time_range=None, intent="lookup"),
        )

        self.assertEqual({node.id for node in expanded.nodes}, {source_id, old_note_id})
        self.assertEqual(expanded.edge_facts[(new_note_id, source_id)], "derived from transcript")
        self.assertEqual(expanded.edge_facts[(new_note_id, old_note_id)], "replaced older note")

    def test_graph_expansion_can_follow_incoming_supersedes_for_relationship_query(self) -> None:
        old_note_id = create_node(self.conn, make_node(title="Old launch target", node_type="note", status="reference"))
        new_note_id = create_node(self.conn, make_node(title="Revised launch target", node_type="note"))
        create_edge(self.conn, make_edge(new_note_id, old_note_id, "SUPERSEDES", fact="updated public launch date"))

        candidate = get_node(self.conn, old_note_id)
        assert candidate is not None

        expanded = expand(
            self.conn,
            [candidate],
            ParsedQuery(
                keywords=["launch", "target"],
                entities=[],
                time_range=None,
                intent="lookup",
                relation_filters=["SUPERSEDES"],
                relation_direction="incoming",
                answer_mode="relationship",
            ),
        )

        self.assertEqual([node.id for node in expanded.nodes], [new_note_id])
        self.assertEqual(expanded.edge_facts[(new_note_id, old_note_id)], "updated public launch date")

    def test_graph_expansion_records_shared_entity_support_path_through_draft_entity(self) -> None:
        routing_note_id = create_node(self.conn, make_node(title="Memory routing idea", node_type="note"))
        article_id = create_node(self.conn, make_node(title="Hierarchical memory article", node_type="source"))
        bridge_entity_id = create_node(
            self.conn,
            make_node(title="Hierarchical Memory", node_type="entity", status="draft"),
        )
        create_edge(self.conn, make_edge(routing_note_id, bridge_entity_id, "REFERS_TO", fact="idea mentions hierarchical memory"))
        create_edge(self.conn, make_edge(article_id, bridge_entity_id, "REFERS_TO", fact="article introduces hierarchical memory"))

        candidate = get_node(self.conn, routing_note_id)
        assert candidate is not None

        expanded = expand(
            self.conn,
            [candidate],
            ParsedQuery(
                keywords=["memory", "routing"],
                entities=["Hierarchical Memory"],
                time_range=None,
                intent="reason",
                answer_mode="relationship",
                question_shape="influence",
            ),
        )

        self.assertEqual([node.id for node in expanded.nodes], [article_id])
        self.assertEqual(len(expanded.support_paths), 1)
        self.assertEqual(expanded.support_paths[0].kind, "shared_entity")
        self.assertEqual(expanded.support_paths[0].bridge_label, "Hierarchical Memory")
        self.assertEqual([segment.relation for segment in expanded.support_paths[0].segments], ["REFERS_TO", "REFERS_TO"])

    def test_graph_expansion_traverses_related_entity_chain(self) -> None:
        routing_note_id = create_node(self.conn, make_node(title="Adaptive memory routing", node_type="note"))
        mcp_note_id = create_node(self.conn, make_node(title="Need to connect MCP orchestration with memory routing", node_type="note"))
        routing_entity_id = create_node(self.conn, make_node(title="Memory Routing", node_type="entity", status="draft"))
        mcp_entity_id = create_node(self.conn, make_node(title="MCP", node_type="entity", status="draft"))
        create_edge(self.conn, make_edge(routing_note_id, routing_entity_id, "REFERS_TO", fact="routing note mentions memory routing"))
        create_edge(self.conn, make_edge(routing_entity_id, mcp_entity_id, "RELATED", fact="memory routing is connected to MCP orchestration"))
        create_edge(self.conn, make_edge(mcp_note_id, mcp_entity_id, "REFERS_TO", fact="note mentions MCP"))

        candidate = get_node(self.conn, routing_note_id)
        assert candidate is not None

        expanded = expand(
            self.conn,
            [candidate],
            ParsedQuery(
                keywords=["mcp", "memory", "connected"],
                entities=["Memory Routing", "MCP"],
                time_range=None,
                intent="lookup",
                relation_filters=["RELATED"],
                answer_mode="relationship",
                question_shape="relationship",
            ),
        )

        self.assertEqual([node.id for node in expanded.nodes], [mcp_note_id])
        self.assertEqual(len(expanded.support_paths), 1)
        self.assertEqual(expanded.support_paths[0].kind, "entity_chain")
        self.assertEqual([segment.relation for segment in expanded.support_paths[0].segments], ["REFERS_TO", "RELATED", "REFERS_TO"])

    def test_graph_expansion_traverses_through_draft_entity_without_surfaceing_it(self) -> None:
        note_id = create_node(self.conn, make_node(title="Python note", content="typing", node_type="note"))
        draft_entity_id = create_node(
            self.conn,
            make_node(title="Python", node_type="entity", status="draft"),
        )
        related_note_id = create_node(
            self.conn,
            make_node(title="Deployment note", content="ops", node_type="note"),
        )
        create_edge(self.conn, make_edge(note_id, draft_entity_id, "REFERS_TO", fact="draft entity mention"))
        create_edge(self.conn, make_edge(related_note_id, draft_entity_id, "REFERS_TO", fact="related draft entity mention"))

        candidate = get_node(self.conn, note_id)
        assert candidate is not None

        expanded = expand(
            self.conn,
            [candidate],
            ParsedQuery(keywords=["python"], entities=["Python"], time_range=None, intent="lookup"),
        )

        self.assertEqual([node.id for node in expanded.nodes], [related_note_id])
        self.assertEqual(expanded.entity_boosted_ids, {note_id})
        self.assertEqual(expanded.edge_facts, {})

    def test_graph_expansion_skips_archived_refers_to_targets(self) -> None:
        note_id = create_node(self.conn, make_node(title="Python note", content="typing", node_type="note"))
        archived_entity_id = create_node(
            self.conn,
            make_node(title="Archived Python", node_type="entity", status="archived"),
        )
        create_edge(self.conn, make_edge(note_id, archived_entity_id, "REFERS_TO", fact="archived entity mention"))

        candidate = get_node(self.conn, note_id)
        assert candidate is not None

        expanded = expand(
            self.conn,
            [candidate],
            ParsedQuery(keywords=["python"], entities=["Archived Python"], time_range=None, intent="lookup"),
        )

        self.assertEqual(expanded.nodes, [])
        self.assertEqual(expanded.entity_boosted_ids, {note_id})

    def test_related_edges_expand_only_for_reason_intent(self) -> None:
        note_id = create_node(self.conn, make_node(title="Start note", node_type="note"))
        related_id = create_node(self.conn, make_node(title="Reasoning note", node_type="note"))
        create_edge(self.conn, make_edge(note_id, related_id, "RELATED", fact="supports inference"))

        candidate = get_node(self.conn, note_id)
        assert candidate is not None

        lookup_expanded = expand(
            self.conn,
            [candidate],
            ParsedQuery(keywords=["start"], entities=[], time_range=None, intent="lookup"),
        )
        reason_expanded = expand(
            self.conn,
            [candidate],
            ParsedQuery(keywords=["start"], entities=[], time_range=None, intent="reason"),
        )

        self.assertEqual(lookup_expanded.nodes, [])
        self.assertEqual([node.id for node in reason_expanded.nodes], [related_id])

    def test_edge_weight_pruning_skips_low_weight_expansion(self) -> None:
        note_id = create_node(self.conn, make_node(title="Main note", node_type="note"))
        entity_id = create_node(self.conn, make_node(title="Low weight entity", node_type="entity"))
        create_edge(self.conn, make_edge(note_id, entity_id, "REFERS_TO", weight=0.2))

        candidate = get_node(self.conn, note_id)
        assert candidate is not None

        expanded = expand(
            self.conn,
            [candidate],
            ParsedQuery(keywords=["main"], entities=["Low weight entity"], time_range=None, intent="lookup"),
        )

        self.assertEqual(expanded.nodes, [])
        self.assertEqual(expanded.entity_boosted_ids, set())

    def test_ranking_score_matches_formula(self) -> None:
        fixed_now = datetime(2026, 4, 22, tzinfo=timezone.utc)
        node = make_node(
            title="Rank me",
            valid_at=fixed_now - timedelta(days=5),
            importance=0.8,
        )

        with mock.patch("pam.retrieval.ranker.utcnow", return_value=fixed_now):
            value, components = score(node, -2.0, True, fixed_now)

        expected_text = abs(-2.0) / (1.0 + abs(-2.0))
        expected_recency = math.exp(-0.01 * 5)
        expected = 0.45 * expected_text + 0.30 * expected_recency + 0.25 * 0.8 + 0.2
        self.assertAlmostEqual(value, expected)
        self.assertEqual(
            value,
            components["text_relevance"]
            + components["recency"]
            + components["importance"]
            + components["entity_bonus"],
        )
        self.assertEqual(components["entity_bonus"], 0.2)

    def test_ranking_prefers_more_negative_fts_rank(self) -> None:
        fixed_now = datetime(2026, 4, 22, tzinfo=timezone.utc)
        node = make_node(title="Comparable", valid_at=fixed_now, importance=0.5)

        better, _ = score(node, -10.0, False, fixed_now)
        worse, _ = score(node, -1.0, False, fixed_now)

        self.assertGreater(better, worse)

    def test_ranker_detects_conflicts_and_increments_access_count(self) -> None:
        first_id = create_node(self.conn, make_node(title="First note", node_type="note", session_id="s-1"))
        second_id = create_node(self.conn, make_node(title="Second note", node_type="note", session_id="s-1"))
        create_edge(self.conn, make_edge(first_id, second_id, "CONTRADICTS"))

        first = get_node(self.conn, first_id)
        second = get_node(self.conn, second_id)
        assert first is not None and second is not None

        with mock.patch("pam.retrieval.ranker.utcnow", return_value=datetime(2026, 4, 22, tzinfo=timezone.utc)):
            result = rank_and_assemble(
                self.conn,
                [(first, -5.0), (second, -3.0)],
                ExpandedResult(nodes=[], edge_facts={}, entity_boosted_ids=set()),
                ParsedQuery(keywords=["note"], entities=[], time_range=None, intent="lookup"),
                top_k=2,
            )

        self.assertEqual(result.conflicts, [(first_id, second_id)])
        self.assertEqual([edge.relation for edge in result.relationships], ["CONTRADICTS"])
        self.assertEqual(result.session_groups, {"s-1": [first_id, second_id]})
        self.assertEqual(get_node(self.conn, first_id).access_count, 1)
        self.assertEqual(get_node(self.conn, second_id).access_count, 1)

    def test_ranker_exposes_score_components_per_surfaced_node(self) -> None:
        note_id = create_node(self.conn, make_node(title="Scored note", node_type="note", importance=0.6))
        graph_only_id = create_node(self.conn, make_node(title="Graph only note", node_type="note", importance=0.4))

        scored = get_node(self.conn, note_id)
        graph_only = get_node(self.conn, graph_only_id)
        assert scored is not None and graph_only is not None

        with mock.patch("pam.retrieval.ranker.utcnow", return_value=datetime(2026, 4, 22, tzinfo=timezone.utc)):
            result = rank_and_assemble(
                self.conn,
                [(scored, -4.0)],
                ExpandedResult(nodes=[graph_only], edge_facts={}, entity_boosted_ids={note_id}),
                ParsedQuery(keywords=["note"], entities=[], time_range=None, intent="lookup"),
                top_k=2,
            )

        self.assertEqual(set(result.score_components), {n.id for n in result.ordered_nodes})
        for node in result.ordered_nodes:
            components = result.score_components[node.id]
            self.assertEqual(
                set(components),
                {"text_relevance", "recency", "importance", "entity_bonus"},
            )
            total, _ = score(
                node,
                -4.0 if node.id == note_id else None,
                node.id == note_id,
                datetime(2026, 4, 22, tzinfo=timezone.utc),
            )
            self.assertEqual(
                total,
                components["text_relevance"]
                + components["recency"]
                + components["importance"]
                + components["entity_bonus"],
            )

        scored_components = result.score_components[note_id]
        graph_components = result.score_components[graph_only_id]
        self.assertGreater(scored_components["text_relevance"], 0.0)
        self.assertEqual(graph_components["text_relevance"], 0.0)
        self.assertGreater(scored_components["entity_bonus"], 0.0)
        self.assertEqual(graph_components["entity_bonus"], 0.0)

    def test_ranker_surfaces_first_class_relationship_hits(self) -> None:
        note_id = create_node(self.conn, make_node(title="Query plan note", node_type="note"))
        source_id = create_node(self.conn, make_node(title="Design source", node_type="source"))
        create_edge(self.conn, make_edge(note_id, source_id, "DERIVED_FROM", fact="captured from design review"))

        note = get_node(self.conn, note_id)
        source = get_node(self.conn, source_id)
        assert note is not None and source is not None

        with mock.patch("pam.retrieval.ranker.utcnow", return_value=datetime(2026, 4, 22, tzinfo=timezone.utc)):
            result = rank_and_assemble(
                self.conn,
                [(note, -5.0), (source, -4.0)],
                ExpandedResult(nodes=[], edge_facts={}, entity_boosted_ids=set()),
                ParsedQuery(
                    keywords=["design"],
                    entities=[],
                    time_range=None,
                    intent="lookup",
                    relation_filters=["DERIVED_FROM"],
                    relation_direction="both",
                    answer_mode="relationship",
                    question_shape="influence",
                ),
                top_k=2,
            )

        self.assertEqual(
            [(edge.source_id, edge.target_id, edge.relation) for edge in result.relationships],
            [(note_id, source_id, "DERIVED_FROM")],
        )
        self.assertEqual(result.query_meta["relation_filters"], ["DERIVED_FROM"])
        self.assertEqual(result.query_meta["relation_direction"], "both")
        self.assertEqual(result.query_meta["answer_mode"], "relationship")
        self.assertEqual(result.query_meta["question_shape"], "influence")
        self.assertEqual(result.graph_explanations[0].title, "Influence path")
        self.assertIn("DERIVED_FROM", result.graph_explanations[0].summary)

    def test_ranker_relationship_query_keeps_best_edge_endpoints_in_results(self) -> None:
        old_note_id = create_node(self.conn, make_node(title="Old launch target", node_type="note", status="reference"))
        new_note_id = create_node(self.conn, make_node(title="Revised launch target", node_type="note"))
        unrelated_id = create_node(self.conn, make_node(title="Launch retro", node_type="note"))
        create_edge(self.conn, make_edge(new_note_id, old_note_id, "SUPERSEDES", fact="public launch moved to April 26"))

        old_note = get_node(self.conn, old_note_id)
        new_note = get_node(self.conn, new_note_id)
        unrelated = get_node(self.conn, unrelated_id)
        assert old_note is not None and new_note is not None and unrelated is not None

        with mock.patch("pam.retrieval.ranker.utcnow", return_value=datetime(2026, 4, 22, tzinfo=timezone.utc)):
            result = rank_and_assemble(
                self.conn,
                [(old_note, -5.0), (unrelated, -4.8)],
                ExpandedResult(
                    nodes=[new_note],
                    edge_facts={(new_note_id, old_note_id): "public launch moved to April 26"},
                    entity_boosted_ids=set(),
                ),
                ParsedQuery(
                    keywords=["launch", "target"],
                    entities=[],
                    time_range=None,
                    intent="lookup",
                    relation_filters=["SUPERSEDES"],
                    relation_direction="incoming",
                    answer_mode="relationship",
                ),
                top_k=2,
            )

        self.assertEqual([node.id for node in result.ordered_nodes], [new_note_id, old_note_id])
        self.assertEqual(
            [(edge.source_id, edge.target_id, edge.relation) for edge in result.relationships],
            [(new_note_id, old_note_id, "SUPERSEDES")],
        )

    def test_ranker_builds_connection_path_from_shared_entity_support(self) -> None:
        routing_note_id = create_node(self.conn, make_node(title="Adaptive memory routing", node_type="note", importance=0.9))
        orchestration_note_id = create_node(self.conn, make_node(title="Connect MCP orchestration with memory routing", node_type="note", importance=0.8))
        bridge_entity_id = create_node(self.conn, make_node(title="Memory Routing", node_type="entity", status="draft"))
        create_edge(self.conn, make_edge(routing_note_id, bridge_entity_id, "REFERS_TO", fact="describes the routing idea"))
        create_edge(self.conn, make_edge(orchestration_note_id, bridge_entity_id, "REFERS_TO", fact="needs routing integration"))

        routing_note = get_node(self.conn, routing_note_id)
        orchestration_note = get_node(self.conn, orchestration_note_id)
        assert routing_note is not None and orchestration_note is not None

        expanded = expand(
            self.conn,
            [routing_note],
            ParsedQuery(
                keywords=["mcp", "memory", "connected"],
                entities=["Memory Routing"],
                time_range=None,
                intent="reason",
                relation_filters=["RELATED"],
                relation_direction="both",
                answer_mode="relationship",
                question_shape="relationship",
                anchor_terms=["MCP"],
            ),
        )

        with mock.patch("pam.retrieval.ranker.utcnow", return_value=datetime(2026, 4, 22, tzinfo=timezone.utc)):
            result = rank_and_assemble(
                self.conn,
                [(routing_note, -5.0)],
                expanded,
                ParsedQuery(
                    keywords=["mcp", "memory", "connected"],
                    entities=["Memory Routing"],
                    time_range=None,
                    intent="reason",
                    relation_filters=["RELATED"],
                    relation_direction="both",
                    answer_mode="relationship",
                    question_shape="relationship",
                    anchor_terms=["MCP"],
                ),
                top_k=3,
            )

        self.assertEqual([node.id for node in result.ordered_nodes[:2]], [routing_note_id, orchestration_note_id])
        self.assertEqual(result.relationships, [])
        self.assertEqual(result.graph_explanations[0].title, "Connection path")
        self.assertIn('connect through "Memory Routing"', result.graph_explanations[0].summary)
        self.assertEqual(len(result.graph_explanations[0].path), 2)

    def test_ranker_builds_connection_path_from_related_entity_chain(self) -> None:
        routing_note_id = create_node(self.conn, make_node(title="Adaptive memory routing", node_type="note", importance=0.9))
        mcp_note_id = create_node(self.conn, make_node(title="Need to connect MCP orchestration with memory routing", node_type="note", importance=0.8))
        routing_entity_id = create_node(self.conn, make_node(title="Memory Routing", node_type="entity", status="draft"))
        mcp_entity_id = create_node(self.conn, make_node(title="MCP", node_type="entity", status="draft"))
        create_edge(self.conn, make_edge(routing_note_id, routing_entity_id, "REFERS_TO", fact="routing note mentions memory routing"))
        create_edge(self.conn, make_edge(routing_entity_id, mcp_entity_id, "RELATED", fact="memory routing is connected to MCP orchestration"))
        create_edge(self.conn, make_edge(mcp_note_id, mcp_entity_id, "REFERS_TO", fact="note mentions MCP"))

        routing_note = get_node(self.conn, routing_note_id)
        assert routing_note is not None
        expanded = expand(
            self.conn,
            [routing_note],
            ParsedQuery(
                keywords=["mcp", "memory", "connected"],
                entities=["Memory Routing", "MCP"],
                time_range=None,
                intent="lookup",
                relation_filters=["RELATED"],
                answer_mode="relationship",
                question_shape="relationship",
                anchor_terms=["MCP"],
            ),
        )

        with mock.patch("pam.retrieval.ranker.utcnow", return_value=datetime(2026, 4, 22, tzinfo=timezone.utc)):
            result = rank_and_assemble(
                self.conn,
                [(routing_note, -5.0)],
                expanded,
                ParsedQuery(
                    keywords=["mcp", "memory", "connected"],
                    entities=["Memory Routing", "MCP"],
                    time_range=None,
                    intent="lookup",
                    relation_filters=["RELATED"],
                    answer_mode="relationship",
                    question_shape="relationship",
                    anchor_terms=["MCP"],
                ),
                top_k=3,
            )

        self.assertEqual([node.id for node in result.ordered_nodes[:2]], [routing_note_id, mcp_note_id])
        self.assertEqual(result.graph_explanations[0].title, "Connection path")
        self.assertIn('through "Memory Routing" and "MCP"', result.graph_explanations[0].summary)
        self.assertEqual([segment.relation for segment in result.graph_explanations[0].path], ["REFERS_TO", "RELATED", "REFERS_TO"])

    def test_ranker_theme_cluster_highlights_central_concepts_from_support_paths(self) -> None:
        routing_note_id = create_node(self.conn, make_node(title="Adaptive memory routing", node_type="note", importance=0.9))
        hot_memory_note_id = create_node(self.conn, make_node(title="Hot memories stay in graph memory", node_type="note", importance=0.7))
        chunking_note_id = create_node(self.conn, make_node(title="Semantic chunk indexing with entity extraction", node_type="note", importance=0.8))
        memory_routing_entity_id = create_node(self.conn, make_node(title="Memory Routing", node_type="entity", status="draft"))
        graph_memory_entity_id = create_node(self.conn, make_node(title="Graph Memory", node_type="entity", status="draft"))
        create_edge(self.conn, make_edge(routing_note_id, memory_routing_entity_id, "REFERS_TO"))
        create_edge(self.conn, make_edge(hot_memory_note_id, memory_routing_entity_id, "REFERS_TO"))
        create_edge(self.conn, make_edge(routing_note_id, graph_memory_entity_id, "REFERS_TO"))
        create_edge(self.conn, make_edge(chunking_note_id, graph_memory_entity_id, "REFERS_TO"))

        routing_note = get_node(self.conn, routing_note_id)
        assert routing_note is not None

        expanded = expand(
            self.conn,
            [routing_note],
            ParsedQuery(
                keywords=["themes", "memory"],
                entities=["Memory Routing", "Graph Memory"],
                time_range=None,
                intent="reason",
                relation_filters=["RELATED"],
                answer_mode="relationship",
                question_shape="theme",
            ),
        )

        with mock.patch("pam.retrieval.ranker.utcnow", return_value=datetime(2026, 4, 22, tzinfo=timezone.utc)):
            result = rank_and_assemble(
                self.conn,
                [(routing_note, -5.0)],
                expanded,
                ParsedQuery(
                    keywords=["themes", "memory"],
                    entities=["Memory Routing", "Graph Memory"],
                    time_range=None,
                    intent="reason",
                    relation_filters=["RELATED"],
                    answer_mode="relationship",
                    question_shape="theme",
                ),
                top_k=4,
            )

        self.assertEqual(result.graph_explanations[0].title, "Theme cluster")
        self.assertIn('"Memory Routing"', result.graph_explanations[0].summary)
        self.assertIn('"Graph Memory"', result.graph_explanations[0].summary)

    def test_ranker_gap_cluster_surfaces_thinly_connected_concepts(self) -> None:
        routing_note_id = create_node(self.conn, make_node(title="Adaptive memory routing", node_type="note", importance=0.9))
        vector_note_id = create_node(self.conn, make_node(title="Cold memories go to vector DB", node_type="note", importance=0.7))
        graph_note_id = create_node(self.conn, make_node(title="Hot memories stay in graph memory", node_type="note", importance=0.7))
        routing_entity_id = create_node(self.conn, make_node(title="Memory Routing", node_type="entity", status="draft"))
        vector_entity_id = create_node(self.conn, make_node(title="Vector DB", node_type="entity", status="draft"))
        graph_entity_id = create_node(self.conn, make_node(title="Graph Memory", node_type="entity", status="draft"))
        create_edge(self.conn, make_edge(routing_note_id, routing_entity_id, "REFERS_TO"))
        create_edge(self.conn, make_edge(vector_note_id, routing_entity_id, "REFERS_TO"))
        create_edge(self.conn, make_edge(routing_note_id, vector_entity_id, "REFERS_TO"))
        create_edge(self.conn, make_edge(routing_note_id, graph_entity_id, "REFERS_TO"))

        routing_note = get_node(self.conn, routing_note_id)
        assert routing_note is not None

        expanded = expand(
            self.conn,
            [routing_note],
            ParsedQuery(
                keywords=["nearby", "topics"],
                entities=["Memory Routing", "Vector DB", "Graph Memory"],
                time_range=None,
                intent="reason",
                relation_filters=["RELATED"],
                answer_mode="relationship",
                question_shape="gap",
            ),
        )

        with mock.patch("pam.retrieval.ranker.utcnow", return_value=datetime(2026, 4, 22, tzinfo=timezone.utc)):
            result = rank_and_assemble(
                self.conn,
                [(routing_note, -5.0)],
                expanded,
                ParsedQuery(
                    keywords=["nearby", "topics"],
                    entities=["Memory Routing", "Vector DB", "Graph Memory"],
                    time_range=None,
                    intent="reason",
                    relation_filters=["RELATED"],
                    answer_mode="relationship",
                    question_shape="gap",
                ),
                top_k=4,
            )

        self.assertEqual(result.graph_explanations[0].title, "Coverage frontier")
        self.assertIn('"Vector DB"', result.graph_explanations[0].summary)
        self.assertIn('"Graph Memory"', result.graph_explanations[0].summary)

    def test_ranker_evolution_query_adds_sequence_summary(self) -> None:
        earliest_id = create_node(
            self.conn,
            make_node(title="Memory matters more than autonomous agents", node_type="note", valid_at=datetime(2026, 4, 18, tzinfo=timezone.utc)),
        )
        middle_id = create_node(
            self.conn,
            make_node(title="Adaptive memory routing", node_type="note", valid_at=datetime(2026, 4, 19, tzinfo=timezone.utc)),
        )
        latest_id = create_node(
            self.conn,
            make_node(title="Connect MCP orchestration with memory routing", node_type="note", valid_at=datetime(2026, 4, 20, tzinfo=timezone.utc)),
        )
        create_edge(self.conn, make_edge(middle_id, earliest_id, "SUPERSEDES", fact="routing idea refined the earlier takeaway"))
        create_edge(self.conn, make_edge(latest_id, middle_id, "SUPERSEDES", fact="MCP integration extends routing work"))

        earliest = get_node(self.conn, earliest_id)
        middle = get_node(self.conn, middle_id)
        latest = get_node(self.conn, latest_id)
        assert earliest is not None and middle is not None and latest is not None

        with mock.patch("pam.retrieval.ranker.utcnow", return_value=datetime(2026, 4, 22, tzinfo=timezone.utc)):
            result = rank_and_assemble(
                self.conn,
                [(earliest, -5.0), (middle, -4.8), (latest, -4.7)],
                expand(
                    self.conn,
                    [earliest, middle, latest],
                    ParsedQuery(
                        keywords=["thinking", "evolved"],
                        entities=[],
                        time_range=None,
                        intent="reason",
                        relation_filters=["SUPERSEDES"],
                        relation_direction="incoming",
                        answer_mode="relationship",
                        question_shape="evolution",
                    ),
                ),
                ParsedQuery(
                    keywords=["thinking", "evolved"],
                    entities=[],
                    time_range=None,
                    intent="reason",
                    relation_filters=["SUPERSEDES"],
                    relation_direction="incoming",
                    answer_mode="relationship",
                    question_shape="evolution",
                ),
                top_k=3,
            )

        self.assertEqual(result.graph_explanations[0].title, "Evolution sequence")
        self.assertIn('"Memory matters more than autonomous agents"', result.graph_explanations[0].summary)
        self.assertIn('"Adaptive memory routing"', result.graph_explanations[0].summary)
        self.assertIn('"Connect MCP orchestration with memory routing"', result.graph_explanations[0].summary)

    def test_ranker_access_count_does_not_refresh_updated_at(self) -> None:
        note_id = create_node(self.conn, make_node(title="Stable freshness", node_type="note"))
        note = get_node(self.conn, note_id)
        self.assertIsNotNone(note)
        assert note is not None
        before_updated_at = note.updated_at

        with mock.patch("pam.retrieval.ranker.utcnow", return_value=datetime(2026, 4, 22, tzinfo=timezone.utc)):
            rank_and_assemble(
                self.conn,
                [(note, -4.0)],
                ExpandedResult(nodes=[], edge_facts={}, entity_boosted_ids=set()),
                ParsedQuery(keywords=["stable"], entities=[], time_range=None, intent="lookup"),
                top_k=1,
            )

        updated = get_node(self.conn, note_id)
        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated.updated_at, before_updated_at)
        self.assertEqual(updated.access_count, 1)

    def test_full_retrieve_pipeline_returns_structured_result_and_logs_query(self) -> None:
        note_id = create_node(
            self.conn,
            make_node(
                title="Python retrieval note",
                content="retrieval pipeline details",
                node_type="note",
                session_id="session-7",
                importance=0.9,
            ),
        )
        entity_id = create_node(self.conn, make_node(title="Python", node_type="entity"))
        source_id = create_node(self.conn, make_node(title="Spec source", node_type="source"))
        create_edge(self.conn, make_edge(note_id, entity_id, "REFERS_TO", fact="mentions Python"))
        create_edge(self.conn, make_edge(note_id, source_id, "DERIVED_FROM", fact="derived from spec"))

        with mock.patch(
            "pam.retrieval.search.parse_query_with_metadata",
            return_value=(
                ParsedQuery(keywords=["Python", "retrieval"], entities=["Python"], time_range=None, intent="lookup"),
                False,
            ),
        ), mock.patch(
            "pam.retrieval.search.get_initialized_connection",
            side_effect=lambda: get_initialized_connection(self.db_path),
        ), mock.patch("pam.retrieval.search.LOG_PATH", self.log_path):
            result = retrieve("Show me the Python retrieval work", top_k=3)

        top_ids = [node.id for node in [*result.notes, *result.entities, *result.sources]]
        self.assertEqual(top_ids, [note_id, entity_id, source_id])
        self.assertEqual([node.id for node in result.ordered_nodes], [note_id, entity_id, source_id])
        self.assertEqual(
            {(edge.source_id, edge.target_id, edge.relation) for edge in result.relationships},
            {(note_id, entity_id, "REFERS_TO"), (note_id, source_id, "DERIVED_FROM")},
        )
        self.assertEqual(result.edge_facts[(note_id, entity_id)], "mentions Python")
        self.assertEqual(result.edge_facts[(note_id, source_id)], "derived from spec")
        self.assertEqual(result.session_groups, {"session-7": [note_id]})

        with self.log_path.open("r", encoding="utf-8") as handle:
            log_record = json.loads(handle.readline())

        self.assertEqual(log_record["event"], "query")
        self.assertEqual(log_record["raw_query"], "Show me the Python retrieval work")
        self.assertEqual(log_record["workspace_id"], resolve_workspace_id())
        self.assertEqual(log_record["returned_count"], 3)
        self.assertEqual(log_record["top_node_ids"], [note_id, entity_id, source_id])

    def test_retrieve_filters_candidates_by_workspace(self) -> None:
        left_workspace = str((Path.cwd() / "workspace-a").resolve())
        right_workspace = str((Path.cwd() / "workspace-b").resolve())
        left_id = create_node(self.conn, make_node(title="Shared note", content="retrieval details", workspace_id=left_workspace))
        create_node(self.conn, make_node(title="Shared note", content="retrieval details", workspace_id=right_workspace))

        with mock.patch(
            "pam.retrieval.query_parser._invoke_llm",
            side_effect=LLMUnavailableError("missing sdk"),
        ), mock.patch(
            "pam.retrieval.search.get_initialized_connection",
            side_effect=lambda: get_initialized_connection(self.db_path),
        ), mock.patch("pam.retrieval.search.LOG_PATH", self.log_path):
            result = retrieve("shared retrieval", top_k=5, workspace_id=left_workspace)

        all_nodes = [*result.events, *result.entities, *result.notes, *result.sources]
        self.assertEqual([node.id for node in all_nodes], [left_id])

        verification_conn = get_connection(self.db_path)
        try:
            self.assertEqual(get_node(verification_conn, left_id).access_count, 1)
        finally:
            verification_conn.close()

    def test_retrieve_initializes_fresh_database_before_querying(self) -> None:
        fresh_db_path = Path(self.temp_dir.name) / "pam-fresh.db"

        with mock.patch(
            "pam.retrieval.query_parser._invoke_llm",
            side_effect=LLMUnavailableError("missing sdk"),
        ), mock.patch(
            "pam.retrieval.search.get_initialized_connection",
            side_effect=lambda: get_initialized_connection(fresh_db_path),
        ), mock.patch("pam.retrieval.search.LOG_PATH", self.log_path):
            result = retrieve("fresh retrieval", top_k=5)

        all_nodes = [*result.events, *result.entities, *result.notes, *result.sources]
        self.assertEqual(all_nodes, [])

        verification_conn = get_connection(fresh_db_path)
        try:
            self.assertEqual(get_current_version(verification_conn), max(MIGRATIONS))
        finally:
            verification_conn.close()

    def test_retrieve_surfaces_related_note_via_draft_entity_bridge(self) -> None:
        with mock.patch("pam.ingestion.pipeline.LOG_PATH", self.log_path), mock.patch(
            "pam.ingestion.pipeline.summarize", return_value=""
        ), mock.patch(
            "pam.ingestion.pipeline.extract_entities", return_value=[{"name": "Python", "category": "tool"}]
        ), mock.patch("pam.ingestion.pipeline.generate_edge_fact", return_value=""):
            parser_note_id = ingest(
                "Parser implementation details",
                input_type="note",
                node_type="note",
                session_id="session-1",
                conn=self.conn,
            )
            deployment_note_id = ingest(
                "Deployment automation work",
                input_type="note",
                node_type="note",
                session_id="session-1",
                conn=self.conn,
            )

        parser_edges = get_edges_from(self.conn, parser_note_id, relation="REFERS_TO")
        self.assertEqual(len(parser_edges), 1)
        entity_node = get_node(self.conn, parser_edges[0].target_id)
        self.assertIsNotNone(entity_node)
        assert entity_node is not None
        self.assertEqual(entity_node.status, "draft")

        result = self._retrieve_with_fallback("parser")

        self.assertEqual(result.entities, [])
        self.assertEqual({node.id for node in result.notes}, {parser_note_id, deployment_note_id})

    def test_regression_corpus_queries_return_expected_hits(self) -> None:
        corpus = self._ingest_regression_corpus()

        for query_case in corpus["queries"]:
            with self.subTest(query=query_case["query"]):
                result = self._retrieve_with_fallback(query_case["query"])
                all_nodes = [*result.events, *result.entities, *result.notes, *result.sources]

                if query_case.get("expect_empty"):
                    self.assertEqual(all_nodes, [])
                    continue

                flattened = self._flatten_result_text(result).lower()
                self.assertTrue(
                    any(expected.lower() in flattened for expected in query_case["expected_substrings"]),
                    msg=(
                        f"Query {query_case['query']!r} did not surface any expected fragment. "
                        f"Returned titles: {[node.title for node in all_nodes]}"
                    ),
                )

    def test_regression_corpus_direct_lookups_keep_exact_note_or_source(self) -> None:
        self._ingest_regression_corpus()
        expected_titles = {
            "What is the stable machine-readable interface for Copilot callers?": "The --json flag is the stable machine-readable interface for",
            "How do valid_at and created_at differ?": "valid_at captures when a fact was true; created_at captures",
            "What limit is used before graph expansion?": "The FTS candidate limit is 50 before graph expansion runs.",
            "How are file ingestions typed?": "File ingestion defaults to source nodes, while plain text no",
            "What do session groups reveal?": "Session groups expose which retrieved nodes came from the sa",
        }

        for query, expected_title_prefix in expected_titles.items():
            with self.subTest(query=query):
                result = self._retrieve_with_fallback(query)
                top_titles = [node.title for node in [*result.notes, *result.sources, *result.events, *result.entities]]
                self.assertTrue(top_titles)
                self.assertEqual(top_titles[0], expected_title_prefix)