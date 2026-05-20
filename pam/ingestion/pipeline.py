from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from config import LOG_PATH, SESSION_STALENESS_HOURS
from pam.db import transaction
from pam.db.edges import Edge, create_edge, get_edges_to
from pam.db.nodes import Node, create_node, get_node, list_nodes, update_node
from pam.db.schema import datetime_to_iso, get_connection, initialize, utcnow
from pam.embeddings import embed_and_store_node
from pam.ingestion.entity_linker import LinkEntitiesResult, link_entities_detailed
from pam.ingestion.extract import extract, infer_node_type
from pam.ingestion.llm import extract_entities, generate_edge_fact, summarize
from pam.ingestion.normalize import normalize
from pam.relations import apply_supersedes


logger = logging.getLogger(__name__)

RELATED_EDGE_WEIGHT = 0.65
ENTITY_CO_MENTION_EDGE_WEIGHT = 0.55
RELATIONSHIP_NODE_TYPES = {"event", "note", "source"}
TOKEN_PATTERN = re.compile(r"\w+")
RELATION_SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+|\n+")
DERIVED_FROM_CUE_PATTERN = re.compile(
    r"\b(derived from|based on|built on|builds on|grew out of|comes from|came from)\b",
    re.IGNORECASE,
)
SUPERSEDES_CUE_PATTERN = re.compile(
    r"\b(revise|revised|revision|replaces|replaced|replacement for|supersedes|superseded|updates|updated version)\b",
    re.IGNORECASE,
)
CONTRADICTS_NEGATIVE_CUE_PATTERN = re.compile(
    r"\b(avoid|avoids|should avoid|do not use|don't use|must not use|reject|rejects|contradict|contradicts)\b",
    re.IGNORECASE,
)
CONTRADICTS_SUPPORT_CUE_PATTERN = re.compile(
    r"\b(is required|requires|can live in|should use|recommended|recommend|prefer|prefers)\b",
    re.IGNORECASE,
)
DERIVED_FROM_EDGE_WEIGHT = 0.9
CONTRADICTS_EDGE_WEIGHT = 0.85


def _append_log_event(payload: dict) -> None:
    from pam.telemetry import append_log_line

    record = {"ts": datetime_to_iso(utcnow()), **payload}
    append_log_line(LOG_PATH, record)


def _log_ingest_event(
    *,
    node_id: str,
    node_type: str,
    input_type: str,
    dedup_hit: bool,
    entities_extracted: int,
    entities_linked_existing: int,
    entities_created_new: int,
    llm_calls: int,
    started_at: float,
) -> None:
    _append_log_event(
        {
            "event": "ingest",
            "node_id": node_id,
            "node_type": node_type,
            "input_type": input_type,
            "dedup_hit": dedup_hit,
            "entities_extracted": entities_extracted,
            "entities_linked_existing": entities_linked_existing,
            "entities_created_new": entities_created_new,
            "llm_calls": llm_calls,
            "duration_ms": int((time.perf_counter() - started_at) * 1000),
        }
    )


def _maybe_warn_session_staleness(
    conn: sqlite3.Connection,
    session_id: str | None,
    recorded_at: datetime,
    force_session: bool,
    workspace_id: str,
) -> None:
    if not session_id or force_session:
        return

    last_in_session = list_nodes(conn, session_id=session_id, workspace_id=workspace_id, limit=1)
    if not last_in_session:
        return

    gap_hours = (recorded_at - last_in_session[0].created_at).total_seconds() / 3600
    if gap_hours > SESSION_STALENESS_HOURS:
        logger.warning("Session %s last active %.0fh ago", session_id, gap_hours)


def _build_main_node(extracted: dict, summary: str) -> Node:
    return Node(
        id="",
        type=extracted["node_type"],
        title=extracted["title"],
        content=extracted["content"],
        summary=summary,
        content_hash=extracted["content_hash"],
        created_at=extracted["created_at"],
        valid_at=extracted["valid_at"],
        updated_at=extracted["updated_at"],
        tags=extracted["tags"],
        session_id=extracted["session_id"],
        importance=extracted["importance"],
        access_count=extracted["access_count"],
        status=extracted["status"],
        metadata=extracted["metadata"],
        workspace_id=extracted["workspace_id"],
    )


def _validate_parent_note_id(conn: sqlite3.Connection, parent_note_id: str) -> None:
    parent = get_node(conn, parent_note_id)
    if parent is None or parent.type != "note":
        raise ValueError("parent_note_id must reference an existing note")


def _create_derived_from_edge(conn: sqlite3.Connection, parent_note_id: str, source_id: str) -> None:
    create_edge(
        conn,
        Edge(
            source_id=parent_note_id,
            target_id=source_id,
            relation="DERIVED_FROM",
            weight=1.0,
            fact="",
            created_at=utcnow(),
        ),
        commit=False,
    )


def _ensure_source_parent_edge(
    conn: sqlite3.Connection,
    *,
    node_type: str,
    parent_note_id: str | None,
    source_id: str,
) -> None:
    if node_type != "source" or not parent_note_id:
        return

    _validate_parent_note_id(conn, parent_note_id)
    _create_derived_from_edge(conn, parent_note_id, source_id)


def _embed_node(
    conn: sqlite3.Connection,
    *,
    node_id: str,
    title: str,
    content: str,
    summary: str,
    entity_names: list[str],
) -> None:
    """Embed and store the main-node vector. No-op if embeddings unavailable."""
    parts = [p for p in (title, summary, content) if p]
    if entity_names:
        parts.append(" ".join(entity_names))
    embed_and_store_node(conn, node_id, " ".join(parts), commit=False)


def _run_llm_enrichment(content: str) -> tuple[str, list[dict], dict[str, str], int]:
    summary = summarize(content)
    entities = extract_entities(content)
    edge_facts = {
        entity["name"]: generate_edge_fact(content, entity["name"])
        for entity in entities
    }
    llm_calls = 2 + len(entities)
    return summary, entities, edge_facts, llm_calls


def _is_relationship_node(node: Node | None) -> bool:
    if node is None:
        return False
    return node.type in RELATIONSHIP_NODE_TYPES and node.status in {"active", "reference"}


def _create_related_edge(
    conn: sqlite3.Connection,
    *,
    source_id: str,
    target_id: str,
    fact: str,
    weight: float,
) -> None:
    if source_id == target_id:
        return
    create_edge(
        conn,
        Edge(
            source_id=source_id,
            target_id=target_id,
            relation="RELATED",
            weight=weight,
            fact=fact,
            created_at=utcnow(),
        ),
        commit=False,
    )


def _create_shared_entity_relationships(
    conn: sqlite3.Connection,
    *,
    node_id: str,
    entity_ids: list[str],
) -> None:
    seen_pairs: set[tuple[str, str]] = set()

    for entity_id in entity_ids:
        entity_node = get_node(conn, entity_id)
        if entity_node is None:
            continue

        for edge in get_edges_to(conn, entity_id, relation="REFERS_TO"):
            other_id = edge.source_id
            if other_id == node_id:
                continue

            other_node = get_node(conn, other_id)
            if not _is_relationship_node(other_node):
                continue

            pair = tuple(sorted((node_id, other_id)))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)

            fact = f'Both reference "{entity_node.title}".'
            _create_related_edge(
                conn,
                source_id=node_id,
                target_id=other_id,
                fact=fact,
                weight=RELATED_EDGE_WEIGHT,
            )
            _create_related_edge(
                conn,
                source_id=other_id,
                target_id=node_id,
                fact=fact,
                weight=RELATED_EDGE_WEIGHT,
            )


def _create_entity_co_mention_relationships(
    conn: sqlite3.Connection,
    *,
    entity_ids: list[str],
    context_title: str,
) -> None:
    unique_entity_ids = list(dict.fromkeys(entity_ids))
    entity_nodes = [(entity_id, get_node(conn, entity_id)) for entity_id in unique_entity_ids]

    for index, (left_id, left_node) in enumerate(entity_nodes):
        if left_node is None:
            continue
        for right_id, right_node in entity_nodes[index + 1 :]:
            if right_node is None:
                continue

            fact = f'Co-mentioned in "{context_title}".'
            _create_related_edge(
                conn,
                source_id=left_id,
                target_id=right_id,
                fact=fact,
                weight=ENTITY_CO_MENTION_EDGE_WEIGHT,
            )
            _create_related_edge(
                conn,
                source_id=right_id,
                target_id=left_id,
                fact=fact,
                weight=ENTITY_CO_MENTION_EDGE_WEIGHT,
            )


def _relation_tokens(text: str) -> set[str]:
    return {token.lower() for token in TOKEN_PATTERN.findall(text or "") if len(token) > 2}


def _cue_fact(content: str, pattern: re.Pattern[str]) -> str:
    for segment in RELATION_SENTENCE_SPLIT_PATTERN.split(content.strip()):
        normalized = " ".join(segment.split())
        if normalized and pattern.search(normalized):
            return normalized
    return ""


def _shared_entity_candidates(
    conn: sqlite3.Connection,
    *,
    node_id: str,
    entity_ids: list[str],
    content: str,
) -> list[tuple[Node, int, int]]:
    if not entity_ids:
        return []

    content_tokens = _relation_tokens(content)
    shared_counts: dict[str, int] = {}
    candidates: dict[str, Node] = {}

    for entity_id in dict.fromkeys(entity_ids):
        for edge in get_edges_to(conn, entity_id, relation="REFERS_TO"):
            other_id = edge.source_id
            if other_id == node_id:
                continue

            other_node = get_node(conn, other_id)
            if not _is_relationship_node(other_node):
                continue

            candidates[other_id] = other_node
            shared_counts[other_id] = shared_counts.get(other_id, 0) + 1

    ranked_candidates: list[tuple[Node, int, int]] = []
    for other_id, other_node in candidates.items():
        title_overlap = len(content_tokens & _relation_tokens(other_node.title))
        ranked_candidates.append((other_node, shared_counts[other_id], title_overlap))

    return ranked_candidates


def _prefer_older_candidates(
    current_node: Node,
    candidates: list[tuple[Node, int, int]],
) -> list[tuple[Node, int, int]]:
    older_candidates = [
        candidate
        for candidate in candidates
        if candidate[0].valid_at <= current_node.valid_at and candidate[0].created_at <= current_node.created_at
    ]
    return older_candidates or candidates


def _select_explicit_relation_target(
    current_node: Node,
    candidates: list[tuple[Node, int, int]],
    relation: str,
) -> Node | None:
    filtered = candidates
    if relation == "SUPERSEDES":
        filtered = [candidate for candidate in candidates if current_node.type == "note" and candidate[0].type == "note"]

    filtered = _prefer_older_candidates(current_node, filtered)
    if not filtered:
        return None

    target, _, _ = max(
        filtered,
        key=lambda candidate: (
            candidate[1],
            candidate[2],
            candidate[0].valid_at,
            candidate[0].created_at,
        ),
    )
    return target


def _select_contradiction_target(
    current_node: Node,
    candidates: list[tuple[Node, int, int]],
) -> tuple[Node | None, str]:
    if current_node.type != "note":
        return None, ""

    note_candidates: list[tuple[Node, int, int, str]] = []
    for candidate_node, shared_count, title_overlap in candidates:
        if candidate_node.type != "note":
            continue

        support_fact = _cue_fact(
            f"{candidate_node.title}\n{candidate_node.content}",
            CONTRADICTS_SUPPORT_CUE_PATTERN,
        )
        if not support_fact:
            continue
        note_candidates.append((candidate_node, shared_count, title_overlap, support_fact))

    if not note_candidates:
        return None, ""

    older_candidates = [
        candidate
        for candidate in note_candidates
        if candidate[0].valid_at <= current_node.valid_at and candidate[0].created_at <= current_node.created_at
    ]
    ranked_candidates = older_candidates or note_candidates
    target, _, _, support_fact = max(
        ranked_candidates,
        key=lambda candidate: (
            candidate[1],
            candidate[2],
            candidate[0].valid_at,
            candidate[0].created_at,
        ),
    )
    return target, support_fact


def _infer_explicit_cross_memory_relations(
    conn: sqlite3.Connection,
    *,
    node_id: str,
    node: Node,
    content: str,
    entity_ids: list[str],
) -> None:
    candidates = _shared_entity_candidates(
        conn,
        node_id=node_id,
        entity_ids=entity_ids,
        content=f"{node.title}\n{content}",
    )
    if not candidates:
        return

    derivation_fact = _cue_fact(content, DERIVED_FROM_CUE_PATTERN)
    if derivation_fact:
        derivation_target = _select_explicit_relation_target(node, candidates, "DERIVED_FROM")
        if derivation_target is not None:
            create_edge(
                conn,
                Edge(
                    source_id=node_id,
                    target_id=derivation_target.id,
                    relation="DERIVED_FROM",
                    weight=DERIVED_FROM_EDGE_WEIGHT,
                    fact=derivation_fact,
                    created_at=utcnow(),
                ),
                commit=False,
            )

    contradiction_fact = _cue_fact(content, CONTRADICTS_NEGATIVE_CUE_PATTERN)
    if contradiction_fact:
        contradiction_target, support_fact = _select_contradiction_target(node, candidates)
        if contradiction_target is not None:
            create_edge(
                conn,
                Edge(
                    source_id=node_id,
                    target_id=contradiction_target.id,
                    relation="CONTRADICTS",
                    weight=CONTRADICTS_EDGE_WEIGHT,
                    fact=f"{contradiction_fact} Conflicts with: {support_fact}",
                    created_at=utcnow(),
                ),
                commit=False,
            )

    supersede_fact = _cue_fact(content, SUPERSEDES_CUE_PATTERN)
    if supersede_fact:
        superseded_target = _select_explicit_relation_target(node, candidates, "SUPERSEDES")
        if superseded_target is None:
            return

        apply_supersedes(
            conn,
            new_node_id=node_id,
            old_node=superseded_target,
            fact=supersede_fact,
            source="ingest_cue",
        )


def ingest(
    raw_text: str,
    input_type: str = "note",
    session_id: str | None = None,
    provided_at: datetime | None = None,
    node_type: str | None = None,
    url: str | None = None,
    workspace_id: str | Path | None = None,
    parent_note_id: str | None = None,
    force_session: bool = False,
    conn: sqlite3.Connection | None = None,
) -> str:
    """
    Full ingestion pipeline. Returns the created node ID or an existing dedup match.
    """
    started_at = time.perf_counter()
    owns_connection = conn is None
    if conn is None:
        conn = get_connection()

    initialize(conn)

    try:
        normalized = normalize(
            raw_text,
            input_type,
            provided_at=provided_at,
            session_id=session_id,
            workspace_id=workspace_id,
        )
        resolved_node_type = infer_node_type(normalized["input_type"], node_type)
        _maybe_warn_session_staleness(
            conn,
            session_id,
            normalized["recorded_at"],
            force_session,
            normalized["workspace_id"],
        )

        extracted = extract(normalized, node_type=node_type, url=url, parent_note_id=parent_note_id, conn=conn)
        if isinstance(extracted, str):
            with transaction(conn):
                _ensure_source_parent_edge(
                    conn,
                    node_type=resolved_node_type,
                    parent_note_id=parent_note_id,
                    source_id=extracted,
                )
            _log_ingest_event(
                node_id=extracted,
                node_type=resolved_node_type,
                input_type=normalized["input_type"],
                dedup_hit=True,
                entities_extracted=0,
                entities_linked_existing=0,
                entities_created_new=0,
                llm_calls=0,
                started_at=started_at,
            )
            return extracted

        summary, entities, edge_facts, llm_calls = _run_llm_enrichment(extracted["content"])

        main_node = _build_main_node(extracted, summary)
        with transaction(conn):
            node_id = create_node(conn, main_node, commit=False)
            _embed_node(
                conn,
                node_id=node_id,
                title=main_node.title,
                content=main_node.content,
                summary=summary,
                entity_names=[e.get("name", "") for e in entities if e.get("name")],
            )
            # TODO: Extend ingest-time graph supply beyond entity mentions so this path can write dependable concept, influence, and evolution edges with explicit evidence.
            link_result = LinkEntitiesResult(entity_ids=[], linked_existing=0, created_new=0)
            if extracted["node_type"] in {"event", "note"}:
                link_result = link_entities_detailed(
                    conn,
                    node_id=node_id,
                    entities=entities,
                    edge_facts=edge_facts,
                    workspace_id=extracted["workspace_id"],
                )

            if extracted["node_type"] in RELATIONSHIP_NODE_TYPES and link_result.entity_ids:
                _create_shared_entity_relationships(
                    conn,
                    node_id=node_id,
                    entity_ids=link_result.entity_ids,
                )
                _create_entity_co_mention_relationships(
                    conn,
                    entity_ids=link_result.entity_ids,
                    context_title=extracted["title"],
                )
                _infer_explicit_cross_memory_relations(
                    conn,
                    node_id=node_id,
                    node=get_node(conn, node_id),
                    content=extracted["content"],
                    entity_ids=link_result.entity_ids,
                )

            _ensure_source_parent_edge(
                conn,
                node_type=extracted["node_type"],
                parent_note_id=extracted.get("parent_note_id"),
                source_id=node_id,
            )

        _log_ingest_event(
            node_id=node_id,
            node_type=extracted["node_type"],
            input_type=normalized["input_type"],
            dedup_hit=False,
            entities_extracted=len(entities),
            entities_linked_existing=link_result.linked_existing,
            entities_created_new=link_result.created_new,
            llm_calls=llm_calls,
            started_at=started_at,
        )
        return node_id
    finally:
        if owns_connection:
            conn.close()


__all__ = ["ingest"]