from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher

from config import (
    ENTITY_CATEGORIES,
    ENTITY_FUZZY_MATCH_THRESHOLD,
    ENTITY_FUZZY_MATCH_THRESHOLD_FTS,
    IMPORTANCE_DEFAULT,
    MAX_ENTITIES_PER_INGESTION,
)
from pam.db import transaction
from pam.db.edges import Edge, create_edge
from pam.db.fts import fts_search_entities
from pam.db.nodes import Node, create_node
from pam.embeddings import embed_and_store_node

try:
    from rapidfuzz.fuzz import token_sort_ratio as _rapidfuzz_token_sort_ratio
except ImportError:  # pragma: no cover - exercised indirectly via fallback behavior
    _rapidfuzz_token_sort_ratio = None


def _token_sort_ratio(left: str, right: str) -> int:
    if _rapidfuzz_token_sort_ratio is not None:
        return int(_rapidfuzz_token_sort_ratio(left, right))
    return int(SequenceMatcher(a=left.lower(), b=right.lower()).ratio() * 100)


@dataclass
class LinkEntitiesResult:
    entity_ids: list[str]
    linked_existing: int
    created_new: int


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _entity_embed_text(node: Node) -> str:
    """Text to embed for an entity node — name + aliases + category."""
    aliases = node.metadata.get("aliases") or []
    if not isinstance(aliases, list):
        aliases = []
    category = node.metadata.get("category") or ""
    parts = [node.title, *(str(a) for a in aliases if a), str(category) if category else ""]
    return " ".join(p for p in parts if p)


def _build_entity_node(name: str, category: str, workspace_id: str | None = None) -> Node:
    timestamp = _utcnow()
    return Node(
        id="",
        type="entity",
        title=name,
        content="",
        summary="",
        content_hash="",
        created_at=timestamp,
        valid_at=timestamp,
        updated_at=timestamp,
        tags=[],
        session_id=None,
        importance=IMPORTANCE_DEFAULT,
        access_count=0,
        status="draft",
        metadata={"aliases": [name], "category": category},
        workspace_id=workspace_id,
    )


def _candidate_names(candidate: Node) -> list[str]:
    names = [candidate.title]
    aliases = candidate.metadata.get("aliases", [])
    if isinstance(aliases, list):
        names.extend(str(alias) for alias in aliases if str(alias).strip())
    return names


def link_entities_detailed(
    conn: sqlite3.Connection,
    node_id: str,
    entities: list[dict],
    edge_facts: dict[str, str],
    content: str,
    workspace_id: str | None = None,
) -> LinkEntitiesResult:
    linked_ids: list[str] = []
    linked_existing = 0
    created_new = 0
    seen_names: set[str] = set()

    del content

    with transaction(conn):
        for entity in entities[:MAX_ENTITIES_PER_INGESTION]:
            entity_name = str(entity.get("name", "")).strip()
            category = str(entity.get("category", "")).strip().lower()
            if not entity_name or category not in ENTITY_CATEGORIES:
                continue

            dedup_key = entity_name.lower()
            if dedup_key in seen_names:
                continue
            seen_names.add(dedup_key)

            candidates = fts_search_entities(conn, entity_name, limit=20, workspace_id=workspace_id)
            best_match = None
            best_score = 0
            for candidate in candidates:
                for candidate_name in _candidate_names(candidate):
                    score = _token_sort_ratio(entity_name, candidate_name)
                    if score > best_score:
                        best_score = score
                        best_match = candidate

            if best_match is not None and (
                best_score >= ENTITY_FUZZY_MATCH_THRESHOLD
                or (candidates and best_score >= ENTITY_FUZZY_MATCH_THRESHOLD_FTS)
            ):
                entity_id = best_match.id
                linked_existing += 1
            else:
                entity_node = _build_entity_node(entity_name, category, workspace_id=workspace_id)
                entity_id = create_node(conn, entity_node, commit=False)
                embed_and_store_node(
                    conn,
                    entity_id,
                    _entity_embed_text(entity_node),
                    commit=False,
                )
                created_new += 1

            create_edge(
                conn,
                Edge(
                    source_id=node_id,
                    target_id=entity_id,
                    relation="REFERS_TO",
                    weight=1.0,
                    fact=edge_facts.get(entity_name, ""),
                    created_at=_utcnow(),
                ),
                commit=False,
            )

            if entity_id not in linked_ids:
                linked_ids.append(entity_id)

    return LinkEntitiesResult(
        entity_ids=linked_ids,
        linked_existing=linked_existing,
        created_new=created_new,
    )


def link_entities(
    conn: sqlite3.Connection,
    node_id: str,
    entities: list[dict],
    edge_facts: dict[str, str],
    content: str,
    workspace_id: str | None = None,
) -> list[str]:
    return link_entities_detailed(conn, node_id, entities, edge_facts, content, workspace_id=workspace_id).entity_ids


__all__ = ["LinkEntitiesResult", "link_entities", "link_entities_detailed"]