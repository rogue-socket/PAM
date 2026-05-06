from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import pam.ingestion.pipeline as pipeline
from pam.db.edges import Edge, create_edge, get_edges_from
from pam.db.nodes import Node, create_node, get_node, update_node
from pam.db.schema import get_connection, get_initialized_connection, initialize
from pam.feedback import supersede
from pam.ingestion.pipeline import ingest
from pam.retrieval.query_parser import ParsedQuery
from pam.retrieval.search import retrieve


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


class RelationSuiteBase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "pam-relations.db"
        self.log_path = Path(self.temp_dir.name) / "pam_log.jsonl"
        self.conn = get_connection(self.db_path)
        initialize(self.conn)

    def tearDown(self) -> None:
        self.conn.close()
        self.temp_dir.cleanup()

    def _ingest_memory(
        self,
        *,
        raw_text: str,
        input_type: str,
        node_type: str | None = None,
        summary: str = "",
        entities: list[dict] | None = None,
        entity_facts: dict[str, str] | None = None,
        parent_note_id: str | None = None,
        url: str | None = None,
        valid_at: datetime | None = None,
        session_id: str | None = None,
    ) -> str:
        facts = entity_facts or {}

        def _fact_for_entity(content: str, entity_name: str) -> str:
            del content
            return facts.get(entity_name, f'This memory references "{entity_name}".')

        with mock.patch.object(pipeline, "LOG_PATH", self.log_path), mock.patch(
            "pam.ingestion.pipeline.summarize", return_value=summary
        ), mock.patch(
            "pam.ingestion.pipeline.extract_entities", return_value=entities or []
        ), mock.patch(
            "pam.ingestion.pipeline.generate_edge_fact", side_effect=_fact_for_entity
        ):
            return ingest(
                raw_text=raw_text,
                input_type=input_type,
                node_type=node_type,
                provided_at=valid_at,
                session_id=session_id,
                parent_note_id=parent_note_id,
                url=url,
                conn=self.conn,
            )

    def _retrieve(self, raw_query: str, *, parsed: ParsedQuery, top_k: int = 6):
        with mock.patch(
            "pam.retrieval.search.parse_query_with_metadata", return_value=(parsed, False)
        ), mock.patch(
            "pam.retrieval.search.get_initialized_connection",
            side_effect=lambda: get_initialized_connection(self.db_path),
        ), mock.patch("pam.retrieval.search.LOG_PATH", self.log_path):
            return retrieve(raw_query, top_k=top_k)

    @staticmethod
    def _all_nodes(result) -> list[Node]:
        return [*result.events, *result.notes, *result.sources, *result.entities]

    def _node_lookup(self, result) -> dict[str, str]:
        return {node.id: node.title for node in self._all_nodes(result)}

    def _relationship_triples(self, result) -> list[tuple[str, str, str]]:
        lookup = self._node_lookup(result)
        return [
            (
                lookup.get(edge.source_id, edge.source_id[:8]),
                edge.relation,
                lookup.get(edge.target_id, edge.target_id[:8]),
            )
            for edge in result.relationships
        ]

    @staticmethod
    def _relationship_id_triples(result) -> set[tuple[str, str, str]]:
        return {(edge.source_id, edge.relation, edge.target_id) for edge in result.relationships}

    def _entity_id_for_note(self, note_id: str, entity_title: str) -> str:
        for edge in get_edges_from(self.conn, note_id, relation="REFERS_TO"):
            target = get_node(self.conn, edge.target_id)
            if target is not None and target.title == entity_title:
                return edge.target_id
        raise AssertionError(f"Missing entity {entity_title!r} for note {note_id}")

    @staticmethod
    def _explanation_named(result, title: str):
        for explanation in result.graph_explanations:
            if explanation.title == title:
                return explanation
        raise AssertionError(f"Missing graph explanation titled {title!r}")


class RelationFormationTests(RelationSuiteBase):
    def test_refers_to_edges_form_for_entity_linked_note_ingestion(self) -> None:
        note_id = self._ingest_memory(
            raw_text="Implemented semantic chunk indexing with entity extraction.",
            input_type="note",
            node_type="note",
            summary="Indexing implementation note.",
            entities=[
                {"name": "Semantic Chunk Indexing", "category": "concept"},
                {"name": "Entity Extraction", "category": "concept"},
            ],
            entity_facts={
                "Semantic Chunk Indexing": "The note implements semantic chunk indexing.",
                "Entity Extraction": "The note depends on entity extraction.",
            },
        )

        edges = get_edges_from(self.conn, note_id, relation="REFERS_TO")

        self.assertEqual(len(edges), 2)
        self.assertEqual({edge.fact for edge in edges}, {
            "The note implements semantic chunk indexing.",
            "The note depends on entity extraction.",
        })

    def test_derived_from_edges_form_when_source_is_attached_to_parent_note(self) -> None:
        note_id = self._ingest_memory(
            raw_text="Idea: adaptive memory routing system.",
            input_type="note",
            node_type="note",
            entities=[{"name": "Memory Routing", "category": "concept"}],
        )

        source_id = self._ingest_memory(
            raw_text="Compound AI systems combine retrieval, planning, memory, and tools.",
            input_type="document",
            summary="Hierarchical memory article.",
            parent_note_id=note_id,
        )

        edges = get_edges_from(self.conn, note_id, relation="DERIVED_FROM")

        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0].target_id, source_id)

    def test_derived_from_edges_can_form_between_notes_from_explicit_cue(self) -> None:
        outline_note_id = self._ingest_memory(
            raw_text="Earlier memory routing outline keeps MCP orchestration tied to retrieval planning.",
            input_type="note",
            node_type="note",
            entities=[
                {"name": "Memory Routing", "category": "concept"},
                {"name": "MCP", "category": "tool"},
            ],
        )

        plan_note_id = self._ingest_memory(
            raw_text="This implementation plan is based on the earlier memory routing outline and keeps MCP orchestration in the loop.",
            input_type="note",
            node_type="note",
            entities=[
                {"name": "Memory Routing", "category": "concept"},
                {"name": "MCP", "category": "tool"},
            ],
        )

        edges = get_edges_from(self.conn, plan_note_id, relation="DERIVED_FROM")

        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0].target_id, outline_note_id)
        self.assertIn("based on", edges[0].fact.lower())

    def test_related_edges_form_between_memories_that_share_a_linked_entity(self) -> None:
        existing_entity_id = create_node(
            self.conn,
            make_node(
                node_type="entity",
                title="MCP",
                status="draft",
                metadata={"aliases": ["MCP"], "category": "tool"},
            ),
        )
        first_note_id = create_node(self.conn, make_node(node_type="note", title="Existing MCP note"))
        create_edge(
            self.conn,
            make_edge(first_note_id, existing_entity_id, "REFERS_TO", fact="The note references MCP."),
        )

        second_note_id = self._ingest_memory(
            raw_text="Need to connect MCP tool orchestration with memory routing.",
            input_type="note",
            node_type="note",
            entities=[{"name": "MCP", "category": "tool"}],
        )

        second_edges = get_edges_from(self.conn, second_note_id, relation="RELATED")
        first_edges = get_edges_from(self.conn, first_note_id, relation="RELATED")

        self.assertEqual([edge.target_id for edge in second_edges], [first_note_id])
        self.assertEqual([edge.target_id for edge in first_edges], [second_note_id])
        self.assertEqual(second_edges[0].fact, 'Both reference "MCP".')

    def test_related_edges_form_between_co_mentioned_entities(self) -> None:
        note_id = self._ingest_memory(
            raw_text="Need to connect MCP tool orchestration with memory routing.",
            input_type="note",
            node_type="note",
            entities=[
                {"name": "MCP", "category": "tool"},
                {"name": "Memory Routing", "category": "concept"},
                {"name": "Tool Orchestration", "category": "concept"},
            ],
        )

        entity_edges = get_edges_from(self.conn, note_id, relation="REFERS_TO")
        entity_ids = [edge.target_id for edge in entity_edges]
        entity_titles = {entity_id: get_node(self.conn, entity_id).title for entity_id in entity_ids}

        related_pairs = {
            (entity_titles[edge.source_id], entity_titles[edge.target_id], edge.fact)
            for entity_id in entity_ids
            for edge in get_edges_from(self.conn, entity_id, relation="RELATED")
            if edge.target_id in entity_titles
        }

        self.assertIn(("MCP", "Memory Routing", 'Co-mentioned in "Need to connect MCP tool orchestration with memory routing.".'), related_pairs)
        self.assertIn(("Memory Routing", "Tool Orchestration", 'Co-mentioned in "Need to connect MCP tool orchestration with memory routing.".'), related_pairs)

    def test_supersedes_edges_form_via_feedback_supersede(self) -> None:
        old_note_id = create_node(self.conn, make_node(node_type="note", title="Memory thesis v1", importance=0.8))
        new_note_id = create_node(self.conn, make_node(node_type="note", title="Memory routing v2", importance=0.7))

        created = supersede(self.conn, new_note_id, old_note_id)

        old_note = get_node(self.conn, old_note_id)
        edges = get_edges_from(self.conn, new_note_id, relation="SUPERSEDES")

        self.assertTrue(created)
        self.assertIsNotNone(old_note)
        assert old_note is not None
        self.assertEqual(old_note.status, "reference")
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0].target_id, old_note_id)

    def test_supersedes_edges_can_form_during_ingest_from_explicit_replacement_cue(self) -> None:
        earlier_note_id = self._ingest_memory(
            raw_text="Harbor Ledger launch target stays at April 18 until invoice export settles.",
            input_type="note",
            node_type="note",
            entities=[
                {"name": "Harbor Ledger", "category": "project"},
                {"name": "Invoice Export", "category": "concept"},
            ],
        )

        revised_note_id = self._ingest_memory(
            raw_text="The new Harbor Ledger launch target replaces the April 18 target because invoice export still slips.",
            input_type="note",
            node_type="note",
            entities=[
                {"name": "Harbor Ledger", "category": "project"},
                {"name": "Invoice Export", "category": "concept"},
            ],
        )

        edges = get_edges_from(self.conn, revised_note_id, relation="SUPERSEDES")
        earlier_note = get_node(self.conn, earlier_note_id)

        self.assertIsNotNone(earlier_note)
        assert earlier_note is not None
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0].target_id, earlier_note_id)
        self.assertIn("replaces", edges[0].fact.lower())
        self.assertEqual(earlier_note.status, "reference")

    def test_supersedes_edges_can_form_during_ingest_from_revision_cue(self) -> None:
        earlier_note_id = self._ingest_memory(
            raw_text="Idea: Aurora Ledger target is 2026-05-19 if the first approval gate clears this week.",
            input_type="note",
            node_type="note",
            entities=[{"name": "Aurora Ledger", "category": "project"}],
        )

        revised_note_id = self._ingest_memory(
            raw_text="Idea: revise Aurora Ledger target to 2026-05-26 because the export checksum still mislabels thawed invoices.",
            input_type="note",
            node_type="note",
            entities=[
                {"name": "Aurora Ledger", "category": "project"},
                {"name": "Export Checksum", "category": "concept"},
            ],
        )

        edges = get_edges_from(self.conn, revised_note_id, relation="SUPERSEDES")
        earlier_note = get_node(self.conn, earlier_note_id)

        self.assertIsNotNone(earlier_note)
        assert earlier_note is not None
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0].target_id, earlier_note_id)
        self.assertIn("revise", edges[0].fact.lower())
        self.assertEqual(earlier_note.status, "reference")

    def test_contradicts_edges_can_form_during_ingest_from_explicit_negation_cue(self) -> None:
        supporting_note_id = self._ingest_memory(
            raw_text="Cold memories can live in vector DB for cheaper storage.",
            input_type="note",
            node_type="note",
            entities=[
                {"name": "Memory Routing", "category": "concept"},
                {"name": "Vector DB", "category": "tool"},
            ],
        )

        contradiction_note_id = self._ingest_memory(
            raw_text="Memory routing should avoid vector databases entirely.",
            input_type="note",
            node_type="note",
            entities=[
                {"name": "Memory Routing", "category": "concept"},
                {"name": "Vector DB", "category": "tool"},
            ],
        )

        edges = get_edges_from(self.conn, contradiction_note_id, relation="CONTRADICTS")

        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0].target_id, supporting_note_id)
        self.assertIn("avoid", edges[0].fact.lower())
        self.assertIn("can live in", edges[0].fact.lower())

    def test_contradicts_edges_can_be_created_for_relation_queries(self) -> None:
        left_id = create_node(self.conn, make_node(node_type="note", title="Vector DB is required"))
        right_id = create_node(self.conn, make_node(node_type="note", title="Avoid vector databases entirely"))

        create_edge(
            self.conn,
            make_edge(
                left_id,
                right_id,
                "CONTRADICTS",
                fact="One note requires vector storage while the other rejects it.",
            ),
        )

        edges = get_edges_from(self.conn, left_id, relation="CONTRADICTS")

        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0].target_id, right_id)
        self.assertEqual(edges[0].fact, "One note requires vector storage while the other rejects it.")


class RelationRetrievalTests(RelationSuiteBase):
    def _seed_relation_corpus(self) -> dict[str, str]:
        thesis_note_id = self._ingest_memory(
            raw_text="Most AI products don't need autonomous agents. They need good memory and retrieval.",
            input_type="note",
            node_type="note",
            summary="Memory matters more than agents.",
            entities=[
                {"name": "Memory", "category": "concept"},
                {"name": "Retrieval", "category": "concept"},
                {"name": "Autonomous Agents", "category": "concept"},
            ],
        )

        routing_note_id = self._ingest_memory(
            raw_text=(
                "Idea: adaptive memory routing system. Hierarchical memory suggests cold memories go to vector DB "
                "while hot memories stay in graph memory."
            ),
            input_type="note",
            node_type="note",
            summary="Adaptive memory routing note.",
            entities=[
                {"name": "Memory Routing", "category": "concept"},
                {"name": "Hierarchical Memory", "category": "concept"},
                {"name": "Vector DB", "category": "tool"},
                {"name": "Graph Memory", "category": "concept"},
            ],
        )

        source_id = self._ingest_memory(
            raw_text="Compound AI systems combine retrieval, planning, memory, and tools. Hierarchical memory improves long-term coherence.",
            input_type="document",
            summary="Hierarchical memory article.",
            parent_note_id=routing_note_id,
        )

        indexing_event_id = self._ingest_memory(
            raw_text="Implemented semantic chunk indexing with entity extraction for memory routing.",
            input_type="task",
            summary="Indexing implementation event.",
            entities=[
                {"name": "Semantic Chunk Indexing", "category": "concept"},
                {"name": "Entity Extraction", "category": "concept"},
                {"name": "Memory Routing", "category": "concept"},
            ],
        )

        mcp_note_id = self._ingest_memory(
            raw_text="Need to connect MCP tool orchestration with memory routing.",
            input_type="note",
            node_type="note",
            summary="MCP integration note.",
            entities=[
                {"name": "MCP", "category": "tool"},
                {"name": "Memory Routing", "category": "concept"},
                {"name": "Tool Orchestration", "category": "concept"},
            ],
        )

        graph_note_id = self._ingest_memory(
            raw_text="Hot memories stay in graph memory for fast architectural recall.",
            input_type="note",
            node_type="note",
            entities=[
                {"name": "Graph Memory", "category": "concept"},
                {"name": "Memory Routing", "category": "concept"},
            ],
        )

        vector_note_id = self._ingest_memory(
            raw_text="Cold memories can live in vector DB for cheaper storage.",
            input_type="note",
            node_type="note",
            entities=[
                {"name": "Vector DB", "category": "tool"},
                {"name": "Memory Routing", "category": "concept"},
            ],
        )

        revised_note_id = self._ingest_memory(
            raw_text="MCP integration is the next step for memory routing.",
            input_type="note",
            node_type="note",
            entities=[
                {"name": "MCP", "category": "tool"},
                {"name": "Memory Routing", "category": "concept"},
            ],
        )

        contradiction_note_id = self._ingest_memory(
            raw_text="Memory routing should avoid vector databases entirely.",
            input_type="note",
            node_type="note",
            entities=[
                {"name": "Memory Routing", "category": "concept"},
                {"name": "Vector DB", "category": "tool"},
            ],
        )

        supersede(self.conn, routing_note_id, thesis_note_id)
        create_edge(
            self.conn,
            make_edge(
                contradiction_note_id,
                vector_note_id,
                "CONTRADICTS",
                fact="One note rejects vector storage while the other recommends it.",
            ),
        )

        return {
            "thesis_note_id": thesis_note_id,
            "routing_note_id": routing_note_id,
            "source_id": source_id,
            "indexing_event_id": indexing_event_id,
            "mcp_note_id": mcp_note_id,
            "graph_note_id": graph_note_id,
            "vector_note_id": vector_note_id,
            "revised_note_id": revised_note_id,
            "contradiction_note_id": contradiction_note_id,
        }

    def test_refers_to_query_retrieves_explicit_relationship_hits(self) -> None:
        ids = self._seed_relation_corpus()

        result = self._retrieve(
            "Which memory mentions MCP?",
            parsed=ParsedQuery(
                keywords=["mcp", "tool", "orchestration", "memory", "routing"],
                entities=["MCP"],
                time_range=None,
                intent="lookup",
                relation_filters=["REFERS_TO"],
                relation_direction="both",
                answer_mode="relationship",
                question_shape="relationship",
                anchor_terms=["MCP"],
            ),
        )

        triples = self._relationship_id_triples(result)
        mcp_entity_id = next(
            edge.target_id for edge in get_edges_from(self.conn, ids["mcp_note_id"], relation="REFERS_TO") if get_node(self.conn, edge.target_id).title == "MCP"
        )
        self.assertTrue(update_node(self.conn, mcp_entity_id, status="active"))

        result = self._retrieve(
            "Which memory mentions MCP?",
            parsed=ParsedQuery(
                keywords=["mcp", "tool", "orchestration", "memory", "routing"],
                entities=["MCP"],
                time_range=None,
                intent="lookup",
                relation_filters=["REFERS_TO"],
                relation_direction="both",
                answer_mode="relationship",
                question_shape="relationship",
                anchor_terms=["MCP"],
            ),
        )

        triples = self._relationship_id_triples(result)
        self.assertIn((ids["mcp_note_id"], "REFERS_TO", mcp_entity_id), triples)
        self.assertIn((ids["revised_note_id"], "REFERS_TO", mcp_entity_id), triples)
        self.assertIn(ids["mcp_note_id"], {node.id for node in self._all_nodes(result)})

    def test_derived_from_query_retrieves_note_to_source_provenance(self) -> None:
        ids = self._seed_relation_corpus()

        result = self._retrieve(
            "What source was my memory routing idea derived from?",
            parsed=ParsedQuery(
                keywords=["memory", "routing", "source"],
                entities=["Memory Routing"],
                time_range=None,
                intent="lookup",
                relation_filters=["DERIVED_FROM"],
                relation_direction="outgoing",
                answer_mode="relationship",
                question_shape="influence",
                anchor_terms=["Memory Routing"],
            ),
        )

        triples = self._relationship_id_triples(result)
        self.assertIn((ids["routing_note_id"], "DERIVED_FROM", ids["source_id"]), triples)
        explanation = self._explanation_named(result, "Influence path")
        self.assertEqual([segment.relation for segment in explanation.path], ["DERIVED_FROM"])

    def test_related_connection_query_retrieves_entity_chain_path(self) -> None:
        ids = self._seed_relation_corpus()

        result = self._retrieve(
            "How are MCP and my memory work connected?",
            parsed=ParsedQuery(
                keywords=["mcp", "memory", "connected"],
                entities=["MCP", "Memory Routing"],
                time_range=None,
                intent="lookup",
                relation_filters=["RELATED"],
                relation_direction="both",
                answer_mode="relationship",
                question_shape="relationship",
                anchor_terms=["MCP", "Memory Routing"],
            ),
        )

        explanation = self._explanation_named(result, "Connection path")
        self.assertIn([segment.relation for segment in explanation.path], (["REFERS_TO", "REFERS_TO"], ["REFERS_TO", "RELATED", "REFERS_TO"]))
        self.assertTrue(
            any(label in explanation.summary for label in ('"Memory Routing"', '"MCP"')),
            explanation.summary,
        )
        returned_ids = {node.id for node in self._all_nodes(result)}
        self.assertIn(ids["mcp_note_id"], returned_ids)
        self.assertTrue(
            ids["routing_note_id"] in returned_ids or ids["revised_note_id"] in returned_ids,
            returned_ids,
        )

    def test_influence_query_retrieves_multiple_supporting_paths(self) -> None:
        ids = self._seed_relation_corpus()

        result = self._retrieve(
            "What influenced my memory routing idea?",
            parsed=ParsedQuery(
                keywords=["memory", "routing", "influenced"],
                entities=["Memory Routing"],
                time_range=None,
                intent="reason",
                relation_filters=[],
                relation_direction=None,
                answer_mode="relationship",
                question_shape="influence",
                anchor_terms=["Memory Routing"],
            ),
            top_k=7,
        )

        returned_ids = {node.id for node in self._all_nodes(result)}
        self.assertIn(ids["indexing_event_id"], returned_ids)
        self.assertIn(ids["mcp_note_id"], returned_ids)
        explanation_titles = {explanation.title for explanation in result.graph_explanations}
        self.assertIn("Influence path", explanation_titles)
        self.assertIn("Influence bridge", explanation_titles)

    def test_supersedes_query_retrieves_current_and_referenced_versions(self) -> None:
        ids = self._seed_relation_corpus()
        supersede(self.conn, ids["revised_note_id"], ids["routing_note_id"])

        result = self._retrieve(
            "What replaced my earlier memory routing note?",
            parsed=ParsedQuery(
                keywords=["replaced", "memory", "routing"],
                entities=["Memory Routing"],
                time_range=None,
                intent="lookup",
                relation_filters=["SUPERSEDES"],
                relation_direction="incoming",
                answer_mode="relationship",
                question_shape="evolution",
                anchor_terms=["Memory Routing"],
            ),
        )

        triples = self._relationship_id_triples(result)
        self.assertIn((ids["revised_note_id"], "SUPERSEDES", ids["routing_note_id"]), triples)
        explanation_titles = {explanation.title for explanation in result.graph_explanations}
        self.assertIn("Evolution path", explanation_titles)
        self.assertIn("Evolution sequence", explanation_titles)
        returned_ids = {node.id for node in self._all_nodes(result)}
        self.assertIn(ids["revised_note_id"], returned_ids)
        self.assertIn(ids["routing_note_id"], returned_ids)

    def test_contradiction_query_retrieves_conflict_edge(self) -> None:
        ids = self._seed_relation_corpus()

        result = self._retrieve(
            "Which notes contradict the vector DB plan?",
            parsed=ParsedQuery(
                keywords=["contradict", "vector", "plan"],
                entities=["Vector DB"],
                time_range=None,
                intent="lookup",
                relation_filters=["CONTRADICTS"],
                relation_direction="both",
                answer_mode="relationship",
                question_shape="relationship",
                anchor_terms=["Vector DB"],
            ),
        )

        triples = self._relationship_id_triples(result)
        self.assertIn((ids["contradiction_note_id"], "CONTRADICTS", ids["vector_note_id"]), triples)
        explanation = self._explanation_named(result, "Conflict edge")
        self.assertEqual([segment.relation for segment in explanation.path], ["CONTRADICTS"])
        returned_ids = {node.id for node in self._all_nodes(result)}
        self.assertIn(ids["contradiction_note_id"], returned_ids)
        self.assertIn(ids["vector_note_id"], returned_ids)

    def test_contradiction_query_retrieves_ingest_inferred_conflict_edge(self) -> None:
        supporting_note_id = self._ingest_memory(
            raw_text="Cold memories can live in vector DB for cheaper storage.",
            input_type="note",
            node_type="note",
            entities=[
                {"name": "Memory Routing", "category": "concept"},
                {"name": "Vector DB", "category": "tool"},
            ],
        )

        contradiction_note_id = self._ingest_memory(
            raw_text="Memory routing should avoid vector databases entirely.",
            input_type="note",
            node_type="note",
            entities=[
                {"name": "Memory Routing", "category": "concept"},
                {"name": "Vector DB", "category": "tool"},
            ],
        )

        result = self._retrieve(
            "Which notes contradict the vector DB plan?",
            parsed=ParsedQuery(
                keywords=["contradict", "vector", "plan"],
                entities=["Memory Routing", "Vector DB"],
                time_range=None,
                intent="lookup",
                relation_filters=["CONTRADICTS"],
                relation_direction="both",
                answer_mode="relationship",
                question_shape="relationship",
                anchor_terms=["Vector DB"],
            ),
        )

        triples = self._relationship_id_triples(result)
        self.assertIn((contradiction_note_id, "CONTRADICTS", supporting_note_id), triples)
        explanation = self._explanation_named(result, "Conflict edge")
        self.assertEqual([segment.relation for segment in explanation.path], ["CONTRADICTS"])

    def test_theme_query_surfaces_central_connected_concepts(self) -> None:
        self._seed_relation_corpus()

        result = self._retrieve(
            "What are the central themes in my research?",
            parsed=ParsedQuery(
                keywords=["central", "themes", "research"],
                entities=["Memory Routing", "MCP", "Graph Memory", "Vector DB"],
                time_range=None,
                intent="reason",
                relation_filters=["RELATED"],
                relation_direction=None,
                answer_mode="relationship",
                question_shape="theme",
                anchor_terms=["Memory Routing", "MCP"],
            ),
            top_k=7,
        )

        explanation = self._explanation_named(result, "Theme cluster")
        self.assertIn('"Memory Routing"', explanation.summary)
        self.assertIn('"MCP"', explanation.summary)
        self.assertTrue(result.graph_explanations)

    def test_gap_query_surfaces_nearby_but_thinly_connected_topics(self) -> None:
        self._seed_relation_corpus()

        result = self._retrieve(
            "What important adjacent topics have I not explored?",
            parsed=ParsedQuery(
                keywords=["adjacent", "topics", "explored"],
                entities=["Memory Routing", "Vector DB", "Graph Memory"],
                time_range=None,
                intent="reason",
                relation_filters=["RELATED"],
                relation_direction=None,
                answer_mode="relationship",
                question_shape="gap",
                anchor_terms=["Memory Routing"],
            ),
            top_k=7,
        )

        explanation = self._explanation_named(result, "Coverage frontier")
        self.assertTrue(
            any(label in explanation.summary for label in ('"Vector DB"', '"Graph Memory"', '"Hierarchical Memory"')),
            explanation.summary,
        )
        self.assertTrue(result.graph_explanations)

    def test_general_lookup_returns_mixed_relation_context_for_relation_dense_corpus(self) -> None:
        self._seed_relation_corpus()

        result = self._retrieve(
            "Show me my memory routing work.",
            parsed=ParsedQuery(
                keywords=["memory", "routing", "work"],
                entities=["Memory Routing"],
                time_range=None,
                intent="lookup",
                relation_filters=[],
                relation_direction=None,
                answer_mode="node",
                question_shape="lookup",
                anchor_terms=["Memory Routing"],
            ),
            top_k=12,
        )

        relations = {edge.relation for edge in result.relationships}
        self.assertIn("RELATED", relations)
        self.assertIn("SUPERSEDES", relations)
        returned_ids = {node.id for node in self._all_nodes(result)}
        self.assertGreaterEqual(len(returned_ids), 8)


class CrossDisciplineRelationTests(RelationSuiteBase):
    def _seed_cross_discipline_corpus(self) -> dict[str, str]:
        biology_note_id = self._ingest_memory(
            raw_text=(
                "Immune memory uses feedback loops to mount faster responses; incident response systems "
                "could borrow that pattern for anomaly handling."
            ),
            input_type="note",
            node_type="note",
            summary="Biology analogy for incident response.",
            entities=[
                {"name": "Immune Memory", "category": "biology"},
                {"name": "Feedback Loops", "category": "concept"},
                {"name": "Incident Response", "category": "operations"},
                {"name": "Anomaly Handling", "category": "concept"},
            ],
        )

        music_note_id = self._ingest_memory(
            raw_text=(
                "Jazz improvisation relies on feedback loops and adaptive handoffs; tool orchestration "
                "should feel more like ensemble listening."
            ),
            input_type="note",
            node_type="note",
            summary="Music analogy for orchestration.",
            entities=[
                {"name": "Jazz Improvisation", "category": "music"},
                {"name": "Feedback Loops", "category": "concept"},
                {"name": "Adaptive Handoff", "category": "concept"},
                {"name": "Tool Orchestration", "category": "concept"},
            ],
        )

        transit_note_id = self._ingest_memory(
            raw_text=(
                "Transit headway control is another feedback-loop discipline; streaming backpressure uses "
                "the same stabilizing idea."
            ),
            input_type="note",
            node_type="note",
            summary="Transit analogy for flow control.",
            entities=[
                {"name": "Headway Control", "category": "urban-planning"},
                {"name": "Feedback Loops", "category": "concept"},
                {"name": "Streaming Backpressure", "category": "engineering"},
                {"name": "Flow Control", "category": "concept"},
            ],
        )

        planning_note_id = self._ingest_memory(
            raw_text=(
                "Protein folding explores energy landscapes; planning search can borrow the same "
                "basin-and-funnel intuition."
            ),
            input_type="note",
            node_type="note",
            summary="Science analogy for planning.",
            entities=[
                {"name": "Protein Folding", "category": "biology"},
                {"name": "Energy Landscapes", "category": "science"},
                {"name": "Planning Search", "category": "ai"},
            ],
        )

        music_source_id = self._ingest_memory(
            raw_text="Cybernetics studies feedback loops across organisms, machines, and music pedagogy.",
            input_type="document",
            summary="Cybernetics source.",
            parent_note_id=music_note_id,
        )

        return {
            "biology_note_id": biology_note_id,
            "music_note_id": music_note_id,
            "transit_note_id": transit_note_id,
            "planning_note_id": planning_note_id,
            "music_source_id": music_source_id,
        }

    def _seed_multihop_evolution_corpus(self) -> dict[str, str]:
        first_note_id = self._ingest_memory(
            raw_text=(
                "Idea: orchestration analogy v1 says immune memory is the best metaphor for incident "
                "orchestration because remembered feedback speeds up the next response."
            ),
            input_type="note",
            node_type="note",
            entities=[
                {"name": "Immune Memory", "category": "biology"},
                {"name": "Incident Orchestration", "category": "operations"},
                {"name": "Feedback", "category": "concept"},
            ],
        )

        second_note_id = self._ingest_memory(
            raw_text=(
                "Idea: orchestration analogy v2 says jazz improvisation explains adaptive handoffs "
                "better than immune memory alone."
            ),
            input_type="note",
            node_type="note",
            entities=[
                {"name": "Jazz Improvisation", "category": "music"},
                {"name": "Adaptive Handoff", "category": "concept"},
                {"name": "Immune Memory", "category": "biology"},
                {"name": "Incident Orchestration", "category": "operations"},
            ],
        )

        third_note_id = self._ingest_memory(
            raw_text=(
                "Idea: orchestration analogy v3 says planning search unifies immune memory and jazz "
                "improvisation into a single orchestration playbook."
            ),
            input_type="note",
            node_type="note",
            entities=[
                {"name": "Planning Search", "category": "ai"},
                {"name": "Immune Memory", "category": "biology"},
                {"name": "Jazz Improvisation", "category": "music"},
                {"name": "Incident Orchestration", "category": "operations"},
            ],
        )

        create_edge(
            self.conn,
            make_edge(
                second_note_id,
                first_note_id,
                "SUPERSEDES",
                fact="The jazz-based orchestration analogy replaces the immune-memory-first version.",
            ),
        )
        create_edge(
            self.conn,
            make_edge(
                third_note_id,
                second_note_id,
                "SUPERSEDES",
                fact="The planning-search version replaces the jazz-handoff revision.",
            ),
        )

        return {
            "first_note_id": first_note_id,
            "second_note_id": second_note_id,
            "third_note_id": third_note_id,
        }

    def test_cross_discipline_refers_to_query_retrieves_shared_concept_mentions(self) -> None:
        ids = self._seed_cross_discipline_corpus()
        feedback_loops_entity_id = self._entity_id_for_note(ids["biology_note_id"], "Feedback Loops")
        self.assertTrue(update_node(self.conn, feedback_loops_entity_id, status="active"))

        result = self._retrieve(
            "Which memories talk about feedback loops across disciplines?",
            parsed=ParsedQuery(
                keywords=["feedback", "loops", "biology", "music", "transit"],
                entities=["Feedback Loops"],
                time_range=None,
                intent="lookup",
                relation_filters=["REFERS_TO"],
                relation_direction="both",
                answer_mode="relationship",
                question_shape="relationship",
                anchor_terms=["Feedback Loops"],
            ),
            top_k=8,
        )

        triples = self._relationship_id_triples(result)
        self.assertIn((ids["biology_note_id"], "REFERS_TO", feedback_loops_entity_id), triples)
        self.assertIn((ids["music_note_id"], "REFERS_TO", feedback_loops_entity_id), triples)
        self.assertIn((ids["transit_note_id"], "REFERS_TO", feedback_loops_entity_id), triples)

    def test_cross_discipline_relationship_query_links_music_and_biology_notes(self) -> None:
        ids = self._seed_cross_discipline_corpus()

        result = self._retrieve(
            "How are my jazz and immune-memory notes connected?",
            parsed=ParsedQuery(
                keywords=["jazz", "immune", "feedback", "connected"],
                entities=["Jazz Improvisation", "Immune Memory", "Feedback Loops"],
                time_range=None,
                intent="lookup",
                relation_filters=["RELATED"],
                relation_direction="both",
                answer_mode="relationship",
                question_shape="relationship",
                anchor_terms=["Jazz Improvisation", "Immune Memory"],
            ),
            top_k=8,
        )

        triples = self._relationship_id_triples(result)
        self.assertTrue(
            (ids["biology_note_id"], "RELATED", ids["music_note_id"]) in triples
            or (ids["music_note_id"], "RELATED", ids["biology_note_id"]) in triples,
            triples,
        )
        self.assertTrue(
            any('"Feedback Loops"' in explanation.summary for explanation in result.graph_explanations),
            [explanation.summary for explanation in result.graph_explanations],
        )
        returned_ids = {node.id for node in self._all_nodes(result)}
        self.assertIn(ids["biology_note_id"], returned_ids)
        self.assertIn(ids["music_note_id"], returned_ids)

    def test_cross_discipline_influence_query_links_music_note_to_source_and_neighbors(self) -> None:
        ids = self._seed_cross_discipline_corpus()

        result = self._retrieve(
            "What influenced my jazz-style orchestration idea?",
            parsed=ParsedQuery(
                keywords=["jazz", "orchestration", "feedback", "influenced"],
                entities=["Jazz Improvisation", "Tool Orchestration"],
                time_range=None,
                intent="reason",
                relation_filters=[],
                relation_direction=None,
                answer_mode="relationship",
                question_shape="influence",
                anchor_terms=["Jazz Improvisation", "Tool Orchestration"],
            ),
            top_k=8,
        )

        explanation_titles = {explanation.title for explanation in result.graph_explanations}
        self.assertIn("Influence path", explanation_titles)
        self.assertIn("Influence bridge", explanation_titles)
        returned_ids = {node.id for node in self._all_nodes(result)}
        self.assertIn(ids["music_note_id"], returned_ids)
        self.assertIn(ids["music_source_id"], returned_ids)
        self.assertTrue(
            ids["biology_note_id"] in returned_ids or ids["transit_note_id"] in returned_ids,
            returned_ids,
        )

    def test_cross_discipline_theme_query_surfaces_feedback_loops_as_bridge(self) -> None:
        ids = self._seed_cross_discipline_corpus()

        result = self._retrieve(
            "What themes connect biology, music, and systems design in my notes?",
            parsed=ParsedQuery(
                keywords=["biology", "music", "systems", "themes", "feedback"],
                entities=["Immune Memory", "Jazz Improvisation", "Feedback Loops", "Headway Control"],
                time_range=None,
                intent="reason",
                relation_filters=["RELATED"],
                relation_direction=None,
                answer_mode="relationship",
                question_shape="theme",
                anchor_terms=["Immune Memory", "Jazz Improvisation", "Feedback Loops"],
            ),
            top_k=8,
        )

        explanation = self._explanation_named(result, "Theme cluster")
        self.assertIn('"Feedback Loops"', explanation.summary)
        returned_ids = {node.id for node in self._all_nodes(result)}
        self.assertIn(ids["biology_note_id"], returned_ids)
        self.assertIn(ids["music_note_id"], returned_ids)
        self.assertIn(ids["transit_note_id"], returned_ids)

    def test_cross_discipline_gap_query_surfaces_lightly_explored_science_analogy(self) -> None:
        ids = self._seed_cross_discipline_corpus()

        result = self._retrieve(
            "What science analogy have I only explored once?",
            parsed=ParsedQuery(
                keywords=["protein", "folding", "planning", "analogy"],
                entities=["Protein Folding", "Energy Landscapes", "Planning Search"],
                time_range=None,
                intent="reason",
                relation_filters=["RELATED"],
                relation_direction=None,
                answer_mode="relationship",
                question_shape="gap",
                anchor_terms=["Planning Search"],
            ),
            top_k=6,
        )

        explanation = self._explanation_named(result, "Coverage frontier")
        self.assertTrue(
            any(
                label in explanation.summary
                for label in ('"Protein Folding"', '"Energy Landscapes"', '"Planning Search"')
            ),
            explanation.summary,
        )
        returned_ids = {node.id for node in self._all_nodes(result)}
        self.assertIn(ids["planning_note_id"], returned_ids)

    def test_cross_discipline_evolution_query_surfaces_multihop_supersession_chain(self) -> None:
        ids = self._seed_multihop_evolution_corpus()

        result = self._retrieve(
            "How did my orchestration analogy evolve from immune memory to planning search?",
            parsed=ParsedQuery(
                keywords=["orchestration", "analogy", "immune", "jazz", "planning"],
                entities=["Immune Memory", "Jazz Improvisation", "Planning Search"],
                time_range=None,
                intent="lookup",
                relation_filters=["SUPERSEDES"],
                relation_direction="both",
                answer_mode="relationship",
                question_shape="evolution",
                anchor_terms=["Immune Memory", "Jazz Improvisation", "Planning Search"],
            ),
            top_k=8,
        )

        triples = self._relationship_id_triples(result)
        self.assertIn((ids["second_note_id"], "SUPERSEDES", ids["first_note_id"]), triples)
        self.assertIn((ids["third_note_id"], "SUPERSEDES", ids["second_note_id"]), triples)
        explanation_titles = {explanation.title for explanation in result.graph_explanations}
        self.assertIn("Evolution path", explanation_titles)
        self.assertIn("Evolution sequence", explanation_titles)
        returned_ids = {node.id for node in self._all_nodes(result)}
        self.assertIn(ids["first_note_id"], returned_ids)
        self.assertIn(ids["second_note_id"], returned_ids)
        self.assertIn(ids["third_note_id"], returned_ids)


if __name__ == "__main__":
    unittest.main()