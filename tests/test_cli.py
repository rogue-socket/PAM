from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock
from uuid import UUID

from click.testing import CliRunner

import cli as cli_module
import pam.db.schema as schema_module
from pam.agent_interface import format_for_context_window, ingest_for_agent, query_for_agent
import pam.chat_agent as chat_agent_module
from pam.chat_agent import ChatResponse
from pam.db.edges import Edge, create_edge
from pam.db.nodes import Node, create_node
from pam.db.schema import get_connection, initialize
from pam.retrieval.ranker import GraphExplanation, GraphPathSegment, RetrievalResult


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
    timestamp = valid_at or datetime(2026, 4, 22, tzinfo=timezone.utc)
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


def make_result(*, notes: list[Node] | None = None, entities: list[Node] | None = None, sources: list[Node] | None = None) -> RetrievalResult:
    return RetrievalResult(
        events=[],
        entities=entities or [],
        notes=notes or [],
        sources=sources or [],
        conflicts=[],
        superseded=[],
        edge_facts={},
        session_groups={},
        query_meta={"keywords": ["pam"]},
    )


def get_cli_output(result) -> str:
    for value in (
        getattr(result, "output", ""),
        getattr(result, "stdout", ""),
        getattr(result, "stderr", ""),
    ):
        if value:
            return value

    for value in (
        getattr(result, "stdout_bytes", b""),
        getattr(result, "stderr_bytes", b""),
        getattr(result, "output_bytes", b""),
    ):
        if value:
            return value.decode("utf-8", errors="replace")

    return ""


class AgentInterfaceTests(unittest.TestCase):
    def test_query_for_agent_delegates_to_retrieve(self) -> None:
        result = make_result()
        with mock.patch("pam.agent_interface.retrieve", return_value=result) as retrieve_mock:
            returned = query_for_agent("what changed", top_k=7)

        self.assertIs(returned, result)
        retrieve_mock.assert_called_once_with("what changed", top_k=7)

    def test_query_for_agent_passes_workspace_id_when_provided(self) -> None:
        result = make_result()
        workspace = Path("tmp-workspace")
        with mock.patch("pam.agent_interface.retrieve", return_value=result) as retrieve_mock:
            returned = query_for_agent("what changed", top_k=7, workspace_id=workspace)

        self.assertIs(returned, result)
        retrieve_mock.assert_called_once_with("what changed", top_k=7, workspace_id=str(workspace))

    def test_ingest_for_agent_routes_source_kind_to_document_ingest(self) -> None:
        with mock.patch("pam.agent_interface.ingest", return_value="node-123") as ingest_mock:
            result = ingest_for_agent(
                "Source body",
                kind="source",
                session_id="session-1",
                valid_at=datetime(2026, 4, 22, tzinfo=timezone.utc),
                workspace_id=Path("/tmp/workspace"),
                parent_note_id="parent-1",
            )

        self.assertEqual(result.node_id, "node-123")
        ingest_mock.assert_called_once_with(
            "Source body",
            input_type="document",
            session_id="session-1",
            provided_at=datetime(2026, 4, 22, tzinfo=timezone.utc),
            node_type="source",
            workspace_id=Path("/tmp/workspace"),
            parent_note_id="parent-1",
        )

    def test_format_for_context_window_includes_sections_and_url_metadata(self) -> None:
        note = make_node(
            node_id="note-1",
            title="CLI wiring",
            summary="Hooked commands into PAM",
            content="Hooked commands into PAM with Click",
        )
        source = make_node(
            node_id="source-1",
            node_type="source",
            title="docs.example.com",
            content="Source content",
            metadata={"url": "https://docs.example.com/cli"},
        )
        result = RetrievalResult(
            events=[],
            entities=[],
            notes=[note],
            sources=[source],
            conflicts=[("note-1", "source-1")],
            superseded=[("source-1", "note-1")],
            edge_facts={("note-1", "source-1"): "note derived from source"},
            session_groups={},
            query_meta={},
            relationships=[
                Edge(
                    source_id="note-1",
                    target_id="source-1",
                    relation="DERIVED_FROM",
                    weight=1.0,
                    fact="note derived from source",
                    created_at=datetime(2026, 4, 22, tzinfo=timezone.utc),
                )
            ],
            graph_explanations=[
                GraphExplanation(
                    kind="path",
                    title="Influence path",
                    summary='"CLI wiring" DERIVED_FROM "docs.example.com" - "note derived from source"',
                    node_ids=["note-1", "source-1"],
                    path=[
                        GraphPathSegment(
                            source_id="note-1",
                            target_id="source-1",
                            relation="DERIVED_FROM",
                            fact="note derived from source",
                        )
                    ],
                    metadata={"relation": "DERIVED_FROM"},
                )
            ],
        )

        rendered = format_for_context_window(result)

        self.assertIn("## Retrieved Memories (2 results)", rendered)
        self.assertIn("### Graph Answer", rendered)
        self.assertIn("### Notes", rendered)
        self.assertIn("### Sources", rendered)
        self.assertIn("[https://docs.example.com/cli] (2026-04-22)", rendered)
        self.assertIn('"CLI wiring" contradicts "docs.example.com"', rendered)
        self.assertIn('"docs.example.com" supersedes "CLI wiring"', rendered)
        self.assertIn('"CLI wiring" DERIVED_FROM "docs.example.com" - "note derived from source"', rendered)

    def test_format_for_context_window_truncation_keeps_referenced_endpoints(self) -> None:
        # 80 notes whose content easily exceeds MAX_CONTEXT_CHARS. A single
        # relationship references the very last note — the one most likely
        # to be cut by naive truncation.
        filler = "x" * 60
        notes = [
            make_node(
                node_id=f"note-{i}",
                title=f"Note {i}",
                summary=f"Summary {i} {filler}",
                content=f"Content {i} {filler}",
            )
            for i in range(80)
        ]
        last_id = notes[-1].id
        first_id = notes[0].id
        relationship = Edge(
            source_id=first_id,
            target_id=last_id,
            relation="REFERS_TO",
            weight=1.0,
            fact="first refers to last",
            created_at=datetime(2026, 4, 22, tzinfo=timezone.utc),
        )

        result = RetrievalResult(
            events=[],
            entities=[],
            notes=notes,
            sources=[],
            conflicts=[],
            superseded=[],
            edge_facts={},
            session_groups={},
            query_meta={"answer_mode": "relationship"},
            relationships=[relationship],
        )

        rendered = format_for_context_window(result)

        self.assertLessEqual(len(rendered), 4000)
        self.assertIn("[truncated]", rendered)
        # The relationship is at the top under relationship-first mode.
        self.assertIn('"Note 0" REFERS_TO "Note 79"', rendered)
        # Both endpoints' detail lines must survive — otherwise the
        # relationship line dangles.
        self.assertIn("[Note 0]", rendered)
        self.assertIn("[Note 79]", rendered)

    def test_format_for_context_window_drops_relationships_whose_endpoints_are_evicted(self) -> None:
        # Construct a case where node lines are kept but a relationship's
        # endpoint lookup id is NOT in any node section. The relationship
        # must be dropped to preserve the no-dangling-reference invariant.
        filler = "y" * 60
        notes = [
            make_node(
                node_id=f"note-{i}",
                title=f"Note {i}",
                summary=f"Summary {i} {filler}",
                content=f"Content {i} {filler}",
            )
            for i in range(80)
        ]
        ghost_relationship = Edge(
            source_id="note-0",
            target_id="ghost-id-not-in-any-section",
            relation="REFERS_TO",
            weight=1.0,
            fact="first refers to ghost",
            created_at=datetime(2026, 4, 22, tzinfo=timezone.utc),
        )

        result = RetrievalResult(
            events=[],
            entities=[],
            notes=notes,
            sources=[],
            conflicts=[],
            superseded=[],
            edge_facts={},
            session_groups={},
            query_meta={"answer_mode": "relationship"},
            relationships=[ghost_relationship],
        )

        rendered = format_for_context_window(result)

        self.assertLessEqual(len(rendered), 4000)
        # Relationship line must NOT appear because its target was never
        # introduced as a node.
        self.assertNotIn("ghost-id-not-in-any-section", rendered)
        self.assertNotIn("first refers to ghost", rendered)


class ChatAgentTests(unittest.TestCase):
    def test_answer_with_pam_uses_retrieved_context_and_prompt_runner(self) -> None:
        retrieved_context = "---\n## Retrieved Memories (1 results)\n### Notes\n- [Inertia] (2026-04-24) - resists changes in motion\n---"
        with mock.patch.object(chat_agent_module, "retrieve_context_for_chat", return_value=retrieved_context) as retrieve_mock, mock.patch.object(
            chat_agent_module,
            "run_copilot_prompt",
            return_value="Inertia is resistance to a change in motion.",
        ) as prompt_mock:
            response = chat_agent_module.answer_with_pam(
                "What is inertia?",
                model="gpt-5.4",
                top_k=3,
                workspace_id=Path("workspace"),
            )

        self.assertEqual(response.answer, "Inertia is resistance to a change in motion.")
        self.assertEqual(response.retrieved_context, retrieved_context)
        retrieve_mock.assert_called_once_with("What is inertia?", top_k=3, workspace_id=Path("workspace"))
        prompt = prompt_mock.call_args.args[0]
        self.assertIn("What is inertia?", prompt)
        self.assertIn("Retrieved Memories", prompt)
        self.assertEqual(prompt_mock.call_args.kwargs["model"], "gpt-5.4")


class CliModuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "pam-cli-test.db"
        self.db_patch = mock.patch.object(schema_module, "DB_PATH", self.db_path)
        self.db_patch.start()
        self.runner = CliRunner()

        conn = get_connection(self.db_path)
        initialize(conn)
        conn.close()

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_session_start_returns_uuid(self) -> None:
        with mock.patch("cli.click.echo") as echo_mock:
            result = self.runner.invoke(cli_module.cli, ["session", "start"])
        output = echo_mock.call_args.args[0]

        self.assertEqual(result.exit_code, 0, output)
        UUID(output.strip())

    def test_add_routes_plain_text_input_to_ingest(self) -> None:
        with mock.patch("cli.ingest", return_value="node-123") as ingest_mock, mock.patch("cli.click.echo") as echo_mock:
            result = self.runner.invoke(
                cli_module.cli,
                ["add", "Remember this", "--type", "note", "--session", "session-1", "--at", "2026-04-22"],
            )
        output = echo_mock.call_args.args[0]

        self.assertEqual(result.exit_code, 0, output)
        self.assertIn("Added: node-123", output)
        called_kwargs = ingest_mock.call_args.kwargs
        self.assertEqual(called_kwargs["raw_text"], "Remember this")
        self.assertEqual(called_kwargs["input_type"], "note")
        self.assertEqual(called_kwargs["session_id"], "session-1")
        self.assertEqual(called_kwargs["node_type"], "note")
        self.assertEqual(called_kwargs["provided_at"], datetime(2026, 4, 22, tzinfo=timezone.utc))
        self.assertIn("conn", called_kwargs)

    def test_query_json_serializes_result(self) -> None:
        note = make_node(node_id="note-1", title="Retrieval note", summary="retrieval summary")
        result_payload = make_result(notes=[note])
        result_payload.relationships = [
            Edge(
                source_id="note-1",
                target_id="source-2",
                relation="RELATED",
                weight=0.7,
                fact="paired during review",
                created_at=datetime(2026, 4, 22, tzinfo=timezone.utc),
            )
        ]
        result_payload.graph_explanations = [
            GraphExplanation(
                kind="path",
                title="Graph relationship",
                summary='"Retrieval note" RELATED "source-2" - "paired during review"',
                node_ids=["note-1", "source-2"],
                path=[
                    GraphPathSegment(
                        source_id="note-1",
                        target_id="source-2",
                        relation="RELATED",
                        fact="paired during review",
                    )
                ],
                metadata={"relation": "RELATED"},
            )
        ]
        with mock.patch("cli.retrieve", return_value=result_payload), mock.patch("cli.click.echo") as echo_mock:
            result = self.runner.invoke(cli_module.cli, ["query", "retrieval", "--json"])
        output = echo_mock.call_args.args[0]

        self.assertEqual(result.exit_code, 0, output)
        payload = json.loads(output)
        self.assertEqual(payload["notes"][0]["id"], "note-1")
        self.assertEqual(payload["notes"][0]["title"], "Retrieval note")
        self.assertEqual(payload["relationships"][0]["relation"], "RELATED")
        self.assertEqual(payload["relationships"][0]["fact"], "paired during review")
        self.assertEqual(payload["graph_explanations"][0]["title"], "Graph relationship")
        self.assertEqual(payload["graph_explanations"][0]["path"][0]["relation"], "RELATED")
        self.assertEqual(payload["query_meta"], {"keywords": ["pam"]})

    def test_query_human_renders_relationship_hits_and_result_sections(self) -> None:
        current_note = make_node(node_id="note-1", title="Launch correction", importance=0.9)
        outdated_note = make_node(node_id="note-2", title="Launch target", importance=0.5)
        source = make_node(node_id="source-1", node_type="source", title="Launch checklist", importance=0.3)
        result_payload = make_result(notes=[current_note, outdated_note], sources=[source])
        result_payload.query_meta = {"answer_mode": "relationship"}
        result_payload.relationships = [
            Edge(
                source_id="note-1",
                target_id="note-2",
                relation="SUPERSEDES",
                weight=1.0,
                fact="moved after invoice export slipped",
                created_at=datetime(2026, 4, 22, tzinfo=timezone.utc),
            )
        ]
        result_payload.graph_explanations = [
            GraphExplanation(
                kind="path",
                title="Evolution path",
                summary='"Launch correction" SUPERSEDES "Launch target" - "moved after invoice export slipped"',
                node_ids=["note-1", "note-2"],
                path=[
                    GraphPathSegment(
                        source_id="note-1",
                        target_id="note-2",
                        relation="SUPERSEDES",
                        fact="moved after invoice export slipped",
                    )
                ],
                metadata={"relation": "SUPERSEDES"},
            )
        ]
        result_payload.conflicts = [("note-1", "note-2")]
        result_payload.superseded = [("note-2", "note-1")]

        with mock.patch("cli.retrieve", return_value=result_payload), mock.patch("cli.click.echo") as echo_mock:
            result = self.runner.invoke(cli_module.cli, ["query", "what replaced the launch target?"])

        output = "\n".join(call.args[0] if call.args else "" for call in echo_mock.call_args_list)
        self.assertEqual(result.exit_code, 0, output)
        self.assertIn("Graph answer:", output)
        self.assertIn('Evolution path: "Launch correction" SUPERSEDES "Launch target" - "moved after invoice export slipped"', output)
        self.assertIn("Found 3 result(s):", output)
        self.assertIn("1. [note] Launch correction", output)
        self.assertIn("Conflicts detected:", output)
        self.assertIn("Superseded nodes in results:", output)

    def test_chat_single_question_prints_answer(self) -> None:
        response = ChatResponse(
            answer="Inertia is resistance to a change in motion.",
            retrieved_context="---\n## Retrieved Memories (1 results)\n---",
        )
        with mock.patch("cli.answer_with_pam", return_value=response) as answer_mock, mock.patch("cli.click.echo") as echo_mock:
            result = self.runner.invoke(cli_module.cli, ["chat", "What is inertia?"])

        output = "\n".join(call.args[0] if call.args else "" for call in echo_mock.call_args_list)
        self.assertEqual(result.exit_code, 0, output)
        answer_mock.assert_called_once_with(
            "What is inertia?",
            model=cli_module.DEFAULT_CHAT_MODEL,
            top_k=5,
            workspace_id=Path.cwd(),
        )
        self.assertIn("Inertia is resistance to a change in motion.", output)

    def test_chat_show_context_prints_context_before_answer(self) -> None:
        response = ChatResponse(
            answer="Entropy tends to increase in an isolated system.",
            retrieved_context="---\n## Retrieved Memories (1 results)\n### Notes\n- [Entropy] (2026-04-24) - tends to increase\n---",
        )
        with mock.patch("cli.answer_with_pam", return_value=response), mock.patch("cli.click.echo") as echo_mock:
            result = self.runner.invoke(cli_module.cli, ["chat", "What does entropy do?", "--show-context"])

        output = "\n".join(call.args[0] if call.args else "" for call in echo_mock.call_args_list)
        self.assertEqual(result.exit_code, 0, output)
        self.assertIn("PAM context:", output)
        self.assertIn("Retrieved Memories", output)
        self.assertIn("Entropy tends to increase in an isolated system.", output)

    def test_chat_interactive_loop_exits_on_blank_input(self) -> None:
        with mock.patch("cli.click.prompt", side_effect=[""]), mock.patch("cli.click.echo") as echo_mock:
            result = self.runner.invoke(cli_module.cli, ["chat"])

        output = "\n".join(call.args[0] if call.args else "" for call in echo_mock.call_args_list)
        self.assertEqual(result.exit_code, 0, output)
        self.assertIn("PAM chat. Submit an empty line to exit.", output)
        self.assertIn("PAM chat ended.", output)

    def test_show_json_reads_from_database(self) -> None:
        conn = get_connection(self.db_path)
        node_id = create_node(conn, make_node(title="Stored note", content="stored content", summary="stored summary"))
        conn.close()

        with mock.patch("cli.click.echo") as echo_mock:
            result = self.runner.invoke(cli_module.cli, ["show", node_id, "--json"])
        output = echo_mock.call_args.args[0]

        self.assertEqual(result.exit_code, 0, output)
        payload = json.loads(output)
        self.assertEqual(payload["id"], node_id)
        self.assertEqual(payload["title"], "Stored note")
        self.assertEqual(payload["summary"], "stored summary")

    def test_show_human_renders_metadata_summary_and_content(self) -> None:
        conn = get_connection(self.db_path)
        node_id = create_node(
            conn,
            make_node(
                title="Stored note",
                content="stored content",
                summary="stored summary",
                tags=["cli", "human"],
                session_id="session-7",
                metadata={"url": "https://docs.example.com/cli"},
            ),
        )
        conn.close()

        with mock.patch("cli.click.echo") as echo_mock:
            result = self.runner.invoke(cli_module.cli, ["show", node_id])

        output = "\n".join(call.args[0] if call.args else "" for call in echo_mock.call_args_list)
        self.assertEqual(result.exit_code, 0, output)
        self.assertIn("Title:        Stored note", output)
        self.assertIn("Tags:         cli, human", output)
        self.assertIn("Session:      session-7", output)
        self.assertIn('Metadata:     {"url": "https://docs.example.com/cli"}', output)
        self.assertIn("Summary: stored summary", output)
        self.assertIn("Content:\nstored content", output)

    def test_graph_lists_incoming_and_outgoing_edges(self) -> None:
        conn = get_connection(self.db_path)
        note_id = create_node(conn, make_node(title="CLI note"))
        entity_id = create_node(conn, make_node(node_type="entity", title="PAM"))
        other_note_id = create_node(conn, make_node(title="Other note"))
        create_edge(
            conn,
            Edge(
                source_id=note_id,
                target_id=entity_id,
                relation="REFERS_TO",
                weight=0.9,
                fact="mentions PAM",
                created_at=datetime(2026, 4, 22, tzinfo=timezone.utc),
            ),
        )
        create_edge(
            conn,
            Edge(
                source_id=other_note_id,
                target_id=note_id,
                relation="RELATED",
                weight=0.5,
                fact="supports CLI note",
                created_at=datetime(2026, 4, 22, tzinfo=timezone.utc),
            ),
        )
        conn.close()

        with mock.patch("cli.click.echo") as echo_mock:
            result = self.runner.invoke(cli_module.cli, ["graph", note_id])
        output = "\n".join(call.args[0] if call.args else "" for call in echo_mock.call_args_list)

        self.assertEqual(result.exit_code, 0, output)
        self.assertIn("Outgoing edges:", output)
        self.assertIn('-> REFERS_TO -> PAM (w=0.90) - "mentions PAM"', output)
        self.assertIn("Incoming edges:", output)
        self.assertIn('<- RELATED <- Other note (w=0.50) - "supports CLI note"', output)


if __name__ == "__main__":
    unittest.main()