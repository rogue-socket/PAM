from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
from unittest.mock import patch

from pam.db.edges import create_edge, get_edges_from
from pam.db.nodes import Node, create_node, get_node, list_nodes
from pam.db.schema import get_connection, initialize, resolve_workspace_id
from pam.ingestion import entity_linker, llm, pipeline
from pam.ingestion.entity_linker import link_entities
from pam.ingestion.extract import FetchedSource, TITLE_MAX_LENGTH, compute_content_hash, extract
from pam.ingestion.normalize import normalize
from pam.ingestion.pipeline import ingest


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


class IngestionModuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = get_connection(":memory:")
        initialize(self.conn)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.log_path = Path(self.temp_dir.name) / "pam_log.jsonl"

    def tearDown(self) -> None:
        self.conn.close()
        self.temp_dir.cleanup()

    def test_normalize_strips_whitespace_and_defaults_provided_at(self) -> None:
        normalized = normalize("  hello world  ", "note")

        self.assertEqual(normalized["raw_text"], "hello world")
        self.assertEqual(normalized["provided_at"], normalized["recorded_at"])
        self.assertEqual(normalized["workspace_id"], resolve_workspace_id())

        with self.assertRaises(ValueError):
            normalize("   ", "note")

    def test_extract_title_rules(self) -> None:
        single_line = "x" * (TITLE_MAX_LENGTH + 10)
        single = extract(normalize(single_line, "note"), conn=self.conn)
        self.assertIsInstance(single, dict)
        assert isinstance(single, dict)
        self.assertEqual(single["title"], single_line[:TITLE_MAX_LENGTH])

        multi = extract(normalize("First line\nSecond line", "note"), conn=self.conn)
        self.assertIsInstance(multi, dict)
        assert isinstance(multi, dict)
        self.assertEqual(multi["title"], "First line")

        with patch("pam.ingestion.extract._fetch_url_content", return_value=None):
            linked = extract(
                normalize("https://docs.python.org/3/", "link"),
                url="https://docs.python.org/3/",
                conn=self.conn,
            )
        self.assertIsInstance(linked, dict)
        assert isinstance(linked, dict)
        self.assertEqual(linked["title"], "docs.python.org")

    def test_compute_content_hash_ignores_whitespace_differences(self) -> None:
        self.assertEqual(compute_content_hash("Hello   world"), compute_content_hash("hello world"))
        self.assertNotEqual(compute_content_hash("Hello world"), compute_content_hash("Different text"))

    def test_extract_returns_existing_id_for_dedup_match(self) -> None:
        existing_id = create_node(
            self.conn,
            make_node(title="Existing", content_hash=compute_content_hash("same content")),
        )

        result = extract(normalize("same   content", "note"), conn=self.conn)
        self.assertEqual(result, existing_id)

    def test_extract_dedups_link_inputs_by_fetched_content_within_workspace(self) -> None:
        with patch(
            "pam.ingestion.extract._fetch_url_content",
            return_value=FetchedSource(title="First", content="first body", content_type="article"),
        ):
            first = extract(normalize("https://example.com/spec", "link"), url="https://example.com/spec", conn=self.conn)

        self.assertIsInstance(first, dict)
        assert isinstance(first, dict)
        create_node(
            self.conn,
            Node(
                id="",
                type=first["node_type"],
                title=first["title"],
                content=first["content"],
                summary=first["summary"],
                content_hash=first["content_hash"],
                created_at=first["created_at"],
                valid_at=first["valid_at"],
                updated_at=first["updated_at"],
                tags=first["tags"],
                session_id=first["session_id"],
                importance=first["importance"],
                access_count=first["access_count"],
                status=first["status"],
                metadata=first["metadata"],
            ),
        )

        with patch(
            "pam.ingestion.extract._fetch_url_content",
            return_value=FetchedSource(title="Second", content="first body", content_type="article"),
        ):
            second = extract(normalize("https://example.com/spec", "link"), url="https://example.com/spec", conn=self.conn)

        self.assertIsInstance(second, str)

    def test_extract_treats_changed_url_content_as_new_memory(self) -> None:
        with patch(
            "pam.ingestion.extract._fetch_url_content",
            return_value=FetchedSource(title="First", content="first body", content_type="article"),
        ):
            first = extract(normalize("https://example.com/spec", "link"), url="https://example.com/spec", conn=self.conn)

        self.assertIsInstance(first, dict)
        assert isinstance(first, dict)
        create_node(
            self.conn,
            Node(
                id="",
                type=first["node_type"],
                title=first["title"],
                content=first["content"],
                summary=first["summary"],
                content_hash=first["content_hash"],
                created_at=first["created_at"],
                valid_at=first["valid_at"],
                updated_at=first["updated_at"],
                tags=first["tags"],
                session_id=first["session_id"],
                importance=first["importance"],
                access_count=first["access_count"],
                status=first["status"],
                metadata=first["metadata"],
                workspace_id=first["workspace_id"],
            ),
        )

        with patch(
            "pam.ingestion.extract._fetch_url_content",
            return_value=FetchedSource(title="Second", content="second body", content_type="article"),
        ):
            second = extract(normalize("https://example.com/spec", "link"), url="https://example.com/spec", conn=self.conn)

        self.assertIsInstance(second, dict)

    def test_extract_scopes_dedup_by_workspace(self) -> None:
        shared_hash = compute_content_hash("same content")
        left_workspace = str((Path.cwd() / "workspace-a").resolve())
        right_workspace = str((Path.cwd() / "workspace-b").resolve())

        create_node(
            self.conn,
            make_node(title="Existing", content_hash=shared_hash, workspace_id=left_workspace),
        )

        result = extract(normalize("same content", "note", workspace_id=right_workspace), conn=self.conn)

        self.assertIsInstance(result, dict)

    def test_fetch_url_content_closes_closable_errors(self) -> None:
        class ClosableError(RuntimeError):
            def __init__(self) -> None:
                super().__init__("boom")
                self.close = mock.Mock()

        error = ClosableError()

        with patch("pam.ingestion.extract.urlopen", side_effect=error):
            self.assertIsNone(extract.__globals__["_fetch_url_content"]("https://example.com/fail"))

        error.close.assert_called_once_with()

    def test_summarize_returns_default_on_failure(self) -> None:
        with patch("pam.ingestion.llm._call_llm", return_value="Short summary"):
            self.assertEqual(llm.summarize("content"), "Short summary")

        with patch("pam.ingestion.llm._call_llm", side_effect=RuntimeError("boom")):
            self.assertEqual(llm.summarize("content"), "")

    def test_extract_entities_validates_json_and_categories(self) -> None:
        payload = '[{"name": "Python", "category": "tool"}, {"name": "Bad", "category": "invalid"}]'
        with patch("pam.ingestion.llm._call_llm", return_value=payload):
            self.assertEqual(llm.extract_entities("content"), [{"name": "Python", "category": "tool"}])

        with patch("pam.ingestion.llm._call_llm", return_value="not json"):
            self.assertEqual(llm.extract_entities("content"), [])

    def test_llm_unavailable_fallback_is_quiet(self) -> None:
        with patch("pam.ingestion.llm._call_llm", side_effect=llm.LLMUnavailableError("missing sdk")), patch(
            "pam.ingestion.llm.logger.warning"
        ) as warning_mock:
            self.assertEqual(llm.summarize("content"), "")
            self.assertEqual(llm.extract_entities("content"), [])
            self.assertEqual(llm.generate_edge_fact("content", "Python"), "")

        warning_mock.assert_not_called()

    def test_entity_linker_matches_existing_entity(self) -> None:
        note_id = create_node(self.conn, make_node(title="Note", node_type="note", content="Used python"))
        existing_id = create_node(
            self.conn,
            make_node(
                title="Python",
                node_type="entity",
                metadata={"aliases": ["Py"], "category": "tool"},
            ),
        )

        linked_ids = link_entities(
            self.conn,
            note_id,
            [{"name": "python", "category": "tool"}],
            {"python": "The note references Python."},
            "Used python",
        )

        self.assertEqual(linked_ids, [existing_id])

    def test_entity_linker_creates_draft_entity_when_no_match_exists(self) -> None:
        note_id = create_node(self.conn, make_node(title="Note", node_type="note"))

        linked_ids = link_entities(
            self.conn,
            note_id,
            [{"name": "PAM", "category": "project"}],
            {"PAM": "The note references PAM."},
            "Building PAM",
        )

        self.assertEqual(len(linked_ids), 1)
        created = get_node(self.conn, linked_ids[0])
        self.assertIsNotNone(created)
        assert created is not None
        self.assertEqual(created.type, "entity")
        self.assertEqual(created.status, "draft")
        self.assertEqual(created.metadata["category"], "project")

    def test_entity_linker_uses_fts_threshold_when_candidate_exists(self) -> None:
        note_id = create_node(self.conn, make_node(title="Note", node_type="note"))
        candidate_id = create_node(
            self.conn,
            make_node(
                node_type="entity",
                title="Py Tool",
                metadata={"aliases": [], "category": "tool"},
            ),
        )
        candidate = get_node(self.conn, candidate_id)
        self.assertIsNotNone(candidate)
        assert candidate is not None

        with patch("pam.ingestion.entity_linker.fts_search_entities", return_value=[candidate]), patch(
            "pam.ingestion.entity_linker._token_sort_ratio", return_value=72
        ):
            linked_ids = link_entities(
                self.conn,
                note_id,
                [{"name": "Python", "category": "tool"}],
                {},
                "Used Python",
            )

        self.assertEqual(linked_ids, [candidate_id])

    def test_entity_linker_creates_forward_refers_to_edge(self) -> None:
        note_id = create_node(self.conn, make_node(title="Note", node_type="note"))

        linked_ids = link_entities(
            self.conn,
            note_id,
            [{"name": "Copilot", "category": "tool"}],
            {"Copilot": "The note mentions Copilot."},
            "Using Copilot",
        )

        self.assertEqual(len(linked_ids), 1)
        outgoing = get_edges_from(self.conn, note_id, relation="REFERS_TO")
        reverse = get_edges_from(self.conn, linked_ids[0], relation="REFERS_TO")
        self.assertEqual(len(outgoing), 1)
        self.assertEqual(outgoing[0].target_id, linked_ids[0])
        self.assertEqual(reverse, [])

    def test_full_pipeline_creates_node_entities_and_edges(self) -> None:
        with patch.object(pipeline, "LOG_PATH", self.log_path), patch(
            "pam.ingestion.pipeline.summarize", return_value="Summary"
        ), patch(
            "pam.ingestion.pipeline.extract_entities", return_value=[{"name": "Python", "category": "tool"}]
        ), patch(
            "pam.ingestion.pipeline.generate_edge_fact", return_value="The note uses Python."
        ):
            node_id = ingest(
                raw_text="Built the ingestion pipeline in Python",
                input_type="task",
                session_id="session-1",
                conn=self.conn,
            )

        created = get_node(self.conn, node_id)
        self.assertIsNotNone(created)
        assert created is not None
        self.assertEqual(created.type, "event")
        self.assertEqual(created.summary, "Summary")

        linked_edges = get_edges_from(self.conn, node_id, relation="REFERS_TO")
        self.assertEqual(len(linked_edges), 1)
        linked_entity = get_node(self.conn, linked_edges[0].target_id)
        self.assertIsNotNone(linked_entity)
        assert linked_entity is not None
        self.assertEqual(linked_entity.title, "Python")
        self.assertEqual(linked_entity.workspace_id, created.workspace_id)
        self.assertTrue(self.log_path.exists())

    def test_pipeline_creates_related_edges_between_memories_sharing_an_entity(self) -> None:
        entity_id = create_node(
            self.conn,
            make_node(
                node_type="entity",
                title="MCP",
                status="draft",
                metadata={"aliases": ["MCP"], "category": "tool"},
            ),
        )
        existing_note_id = create_node(self.conn, make_node(node_type="note", title="Earlier MCP note"))
        create_edge(
            self.conn,
            pipeline.Edge(
                source_id=existing_note_id,
                target_id=entity_id,
                relation="REFERS_TO",
                weight=1.0,
                fact="Earlier note mentions MCP.",
                created_at=datetime.now(timezone.utc),
            ),
        )

        with patch.object(pipeline, "LOG_PATH", self.log_path), patch(
            "pam.ingestion.pipeline.summarize", return_value=""
        ), patch(
            "pam.ingestion.pipeline.extract_entities", return_value=[{"name": "MCP", "category": "tool"}]
        ), patch(
            "pam.ingestion.pipeline.generate_edge_fact", return_value="The note references MCP."
        ):
            new_note_id = ingest(
                raw_text="Need to connect MCP orchestration with memory routing.",
                input_type="note",
                node_type="note",
                conn=self.conn,
            )

        outgoing = get_edges_from(self.conn, new_note_id, relation="RELATED")
        reverse = get_edges_from(self.conn, existing_note_id, relation="RELATED")
        self.assertEqual([edge.target_id for edge in outgoing], [existing_note_id])
        self.assertEqual([edge.target_id for edge in reverse], [new_note_id])
        self.assertEqual(outgoing[0].fact, 'Both reference "MCP".')

    def test_pipeline_creates_related_edges_between_co_mentioned_entities(self) -> None:
        with patch.object(pipeline, "LOG_PATH", self.log_path), patch(
            "pam.ingestion.pipeline.summarize", return_value=""
        ), patch(
            "pam.ingestion.pipeline.extract_entities",
            return_value=[
                {"name": "MCP", "category": "tool"},
                {"name": "Memory Routing", "category": "concept"},
            ],
        ), patch(
            "pam.ingestion.pipeline.generate_edge_fact", return_value=""
        ):
            note_id = ingest(
                raw_text="Memory routing with MCP",
                input_type="note",
                node_type="note",
                conn=self.conn,
            )

        linked_entities = get_edges_from(self.conn, note_id, relation="REFERS_TO")
        self.assertEqual(len(linked_entities), 2)
        first_entity_id = linked_entities[0].target_id
        second_entity_id = linked_entities[1].target_id

        first_related = get_edges_from(self.conn, first_entity_id, relation="RELATED")
        second_related = get_edges_from(self.conn, second_entity_id, relation="RELATED")
        self.assertEqual([edge.target_id for edge in first_related], [second_entity_id])
        self.assertEqual([edge.target_id for edge in second_related], [first_entity_id])
        self.assertEqual(first_related[0].fact, 'Co-mentioned in "Memory routing with MCP".')

    def test_pipeline_can_link_source_to_parent_note(self) -> None:
        parent_note_id = create_node(self.conn, make_node(node_type="note", title="Parent note"))

        with patch.object(pipeline, "LOG_PATH", self.log_path), patch(
            "pam.ingestion.pipeline.summarize", return_value=""
        ), patch("pam.ingestion.pipeline.extract_entities", return_value=[]), patch(
            "pam.ingestion.pipeline.generate_edge_fact", return_value=""
        ):
            source_id = ingest(
                raw_text="https://example.com/spec",
                input_type="link",
                url="https://example.com/spec",
                parent_note_id=parent_note_id,
                conn=self.conn,
            )

        derived_edges = get_edges_from(self.conn, parent_note_id, relation="DERIVED_FROM")
        self.assertEqual(len(derived_edges), 1)
        self.assertEqual(derived_edges[0].target_id, source_id)

    def test_pipeline_adds_parent_edge_when_dedup_returns_existing_source(self) -> None:
        parent_note_id = create_node(self.conn, make_node(node_type="note", title="Parent note"))
        with patch.object(pipeline, "LOG_PATH", self.log_path), patch(
            "pam.ingestion.pipeline.summarize", return_value=""
        ), patch("pam.ingestion.pipeline.extract_entities", return_value=[]), patch(
            "pam.ingestion.pipeline.generate_edge_fact", return_value=""
        ):
            source_id = ingest(
                raw_text="https://example.com/spec",
                input_type="link",
                url="https://example.com/spec",
                conn=self.conn,
            )
            returned_id = ingest(
                raw_text="https://example.com/spec",
                input_type="link",
                url="https://example.com/spec",
                parent_note_id=parent_note_id,
                conn=self.conn,
            )

        self.assertEqual(returned_id, source_id)
        derived_edges = get_edges_from(self.conn, parent_note_id, relation="DERIVED_FROM")
        self.assertEqual(len(derived_edges), 1)
        self.assertEqual(derived_edges[0].target_id, source_id)

    def test_pipeline_rolls_back_node_when_entity_linking_fails(self) -> None:
        with patch.object(pipeline, "LOG_PATH", self.log_path), patch(
            "pam.ingestion.pipeline.summarize", return_value="Summary"
        ), patch(
            "pam.ingestion.pipeline.extract_entities", return_value=[{"name": "Python", "category": "tool"}]
        ), patch(
            "pam.ingestion.pipeline.generate_edge_fact", return_value="The note uses Python."
        ), patch(
            "pam.ingestion.pipeline.link_entities_detailed", side_effect=RuntimeError("entity linking failed")
        ):
            with self.assertRaisesRegex(RuntimeError, "entity linking failed"):
                ingest(
                    raw_text="Built the ingestion pipeline in Python",
                    input_type="task",
                    session_id="session-1",
                    conn=self.conn,
                )

        self.assertEqual(list_nodes(self.conn, limit=None), [])
        self.assertFalse(self.log_path.exists())

    def test_pipeline_rejects_non_note_parent_for_source_provenance(self) -> None:
        parent_event_id = create_node(self.conn, make_node(node_type="event", title="Parent event"))

        with self.assertRaises(ValueError):
            ingest(
                raw_text="https://example.com/spec",
                input_type="link",
                url="https://example.com/spec",
                parent_note_id=parent_event_id,
                conn=self.conn,
            )

    def test_session_staleness_logs_warning_without_blocking_ingestion(self) -> None:
        stale_at = datetime.now(timezone.utc) - timedelta(days=2)
        create_node(
            self.conn,
            make_node(
                title="Earlier session work",
                node_type="event",
                session_id="session-1",
                valid_at=stale_at,
            ),
        )

        with patch.object(pipeline, "LOG_PATH", self.log_path), patch(
            "pam.ingestion.pipeline.summarize", return_value=""
        ), patch(
            "pam.ingestion.pipeline.extract_entities", return_value=[]
        ), patch(
            "pam.ingestion.pipeline.logger.warning"
        ) as warning_mock:
            node_id = ingest(
                raw_text="Current session work",
                input_type="task",
                session_id="session-1",
                provided_at=datetime.now(timezone.utc),
                conn=self.conn,
            )

        self.assertTrue(warning_mock.called)
        session_nodes = list_nodes(self.conn, session_id="session-1")
        self.assertIn(node_id, {node.id for node in session_nodes})

    def test_session_staleness_ignores_backdated_fact_time_when_activity_is_fresh(self) -> None:
        with patch.object(pipeline, "LOG_PATH", self.log_path), patch(
            "pam.ingestion.pipeline.summarize", return_value=""
        ), patch(
            "pam.ingestion.pipeline.extract_entities", return_value=[]
        ), patch(
            "pam.ingestion.pipeline.logger.warning"
        ) as warning_mock:
            ingest(
                raw_text="Backfilled earlier work",
                input_type="task",
                session_id="session-1",
                provided_at=datetime.now(timezone.utc) - timedelta(days=3),
                conn=self.conn,
            )
            node_id = ingest(
                raw_text="Current follow-up",
                input_type="task",
                session_id="session-1",
                provided_at=datetime.now(timezone.utc),
                conn=self.conn,
            )

        warning_mock.assert_not_called()
        session_nodes = list_nodes(self.conn, session_id="session-1")
        self.assertIn(node_id, {node.id for node in session_nodes})


if __name__ == "__main__":
    unittest.main()