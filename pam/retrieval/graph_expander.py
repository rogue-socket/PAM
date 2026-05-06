from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from config import EDGE_WEIGHT_EXPANSION_THRESHOLD
from pam.db.edges import get_edges_from, get_edges_to
from pam.db.nodes import Node, get_node
from pam.retrieval.query_parser import ParsedQuery


@dataclass
class ExpandedResult:
    nodes: list[Node]
    edge_facts: dict[tuple[str, str], str]
    entity_boosted_ids: set[str]
    support_paths: list["ExpandedPath"] = field(default_factory=list)


@dataclass
class ExpandedPathSegment:
    source_id: str
    target_id: str
    relation: str
    fact: str = ""
    source_label: str = ""
    target_label: str = ""


@dataclass
class ExpandedPath:
    kind: str
    anchor_id: str
    related_id: str
    bridge_id: str | None = None
    anchor_label: str = ""
    related_label: str = ""
    bridge_label: str = ""
    segments: list[ExpandedPathSegment] = field(default_factory=list)
    score: float = 0.0


def _record_edge_fact(edge_facts: dict[tuple[str, str], str], source_id: str, target_id: str, fact: str) -> None:
    if fact:
        edge_facts[(source_id, target_id)] = fact


def _add_node_if_new(seen: set[str], expanded_nodes: list[Node], node: Node | None) -> None:
    if node is None or node.id in seen:
        return
    seen.add(node.id)
    expanded_nodes.append(node)


def _is_surfaceable(node: Node | None, *, allow_reference: bool = False) -> bool:
    if node is None:
        return False
    if node.status == "active":
        return True
    return allow_reference and node.status == "reference"


def _is_traversable(node: Node | None, *, allow_reference: bool = False) -> bool:
    if node is None:
        return False
    if _is_surfaceable(node, allow_reference=allow_reference):
        return True
    return node.type == "entity" and node.status == "draft"


def _weighted_edges(edges: list) -> list:
    return [edge for edge in edges if edge.weight >= EDGE_WEIGHT_EXPANSION_THRESHOLD]


def _should_expand_related_concepts(parsed: ParsedQuery) -> bool:
    return parsed.intent == "reason" or "RELATED" in parsed.relation_filters


def _node_label(node: Node | None, fallback: str) -> str:
    if node is None:
        return fallback[:8]
    return (node.title or node.summary or node.id[:8]).strip()


def _build_path_segment(
    *,
    source_id: str,
    target_id: str,
    relation: str,
    fact: str,
    source_label: str,
    target_label: str,
) -> ExpandedPathSegment:
    return ExpandedPathSegment(
        source_id=source_id,
        target_id=target_id,
        relation=relation,
        fact=fact,
        source_label=source_label,
        target_label=target_label,
    )


def _path_key(path: ExpandedPath) -> tuple:
    return (
        path.kind,
        path.anchor_id,
        path.related_id,
        path.bridge_id,
        tuple((segment.source_id, segment.target_id, segment.relation) for segment in path.segments),
    )


def _record_support_path(
    support_paths: list[ExpandedPath],
    seen_paths: set[tuple],
    path: ExpandedPath,
) -> None:
    key = _path_key(path)
    if key in seen_paths:
        return
    seen_paths.add(key)
    support_paths.append(path)


def _expand_outgoing_relation(
    conn: sqlite3.Connection,
    *,
    node_id: str,
    node_label: str,
    relation: str,
    seen: set[str],
    expanded_nodes: list[Node],
    edge_facts: dict[tuple[str, str], str],
    support_paths: list[ExpandedPath],
    seen_support_paths: set[tuple],
    allow_reference: bool = False,
) -> None:
    for edge in _weighted_edges(get_edges_from(conn, node_id, relation=relation)):
        target = get_node(conn, edge.target_id)
        if not _is_surfaceable(target, allow_reference=allow_reference):
            continue

        _record_edge_fact(edge_facts, edge.source_id, edge.target_id, edge.fact)
        _add_node_if_new(seen, expanded_nodes, target)
        _record_support_path(
            support_paths,
            seen_support_paths,
            ExpandedPath(
                kind="direct_edge",
                anchor_id=node_id,
                related_id=edge.target_id,
                anchor_label=node_label,
                related_label=_node_label(target, edge.target_id),
                segments=[
                    _build_path_segment(
                        source_id=edge.source_id,
                        target_id=edge.target_id,
                        relation=edge.relation,
                        fact=edge.fact,
                        source_label=node_label,
                        target_label=_node_label(target, edge.target_id),
                    )
                ],
                score=edge.weight,
            ),
        )


def _expand_requested_relationships(
    conn: sqlite3.Connection,
    candidates: list[Node],
    parsed: ParsedQuery,
    seen: set[str],
    expanded_nodes: list[Node],
    edge_facts: dict[tuple[str, str], str],
    support_paths: list[ExpandedPath],
    seen_support_paths: set[tuple],
) -> None:
    if not parsed.relation_filters:
        return

    requested_relations = set(parsed.relation_filters)
    directions = ["incoming", "outgoing"] if parsed.relation_direction in {None, "both"} else [parsed.relation_direction]

    for node in candidates:
        if "outgoing" in directions:
            for edge in _weighted_edges(get_edges_from(conn, node.id)):
                if edge.relation not in requested_relations:
                    continue

                allow_reference = edge.relation == "SUPERSEDES"
                target = get_node(conn, edge.target_id)
                if not _is_surfaceable(target, allow_reference=allow_reference):
                    continue

                _record_edge_fact(edge_facts, edge.source_id, edge.target_id, edge.fact)
                _add_node_if_new(seen, expanded_nodes, target)
                _record_support_path(
                    support_paths,
                    seen_support_paths,
                    ExpandedPath(
                        kind="direct_edge",
                        anchor_id=node.id,
                        related_id=edge.target_id,
                        anchor_label=_node_label(node, node.id),
                        related_label=_node_label(target, edge.target_id),
                        segments=[
                            _build_path_segment(
                                source_id=edge.source_id,
                                target_id=edge.target_id,
                                relation=edge.relation,
                                fact=edge.fact,
                                source_label=_node_label(node, node.id),
                                target_label=_node_label(target, edge.target_id),
                            )
                        ],
                        score=edge.weight,
                    ),
                )

        if "incoming" in directions:
            for edge in _weighted_edges(get_edges_to(conn, node.id)):
                if edge.relation not in requested_relations:
                    continue

                source = get_node(conn, edge.source_id)
                if not _is_surfaceable(source):
                    continue

                _record_edge_fact(edge_facts, edge.source_id, edge.target_id, edge.fact)
                _add_node_if_new(seen, expanded_nodes, source)
                _record_support_path(
                    support_paths,
                    seen_support_paths,
                    ExpandedPath(
                        kind="direct_edge",
                        anchor_id=node.id,
                        related_id=edge.source_id,
                        anchor_label=_node_label(node, node.id),
                        related_label=_node_label(source, edge.source_id),
                        segments=[
                            _build_path_segment(
                                source_id=edge.source_id,
                                target_id=edge.target_id,
                                relation=edge.relation,
                                fact=edge.fact,
                                source_label=_node_label(source, edge.source_id),
                                target_label=_node_label(node, node.id),
                            )
                        ],
                        score=edge.weight,
                    ),
                )


def expand(conn: sqlite3.Connection, candidates: list[Node], parsed: ParsedQuery) -> ExpandedResult:
    # TODO: Add constrained multi-hop traversal and path provenance so graph answers are assembled from supported chains, not only one-hop expansion.
    seen = {node.id for node in candidates}
    expanded_nodes: list[Node] = []
    edge_facts: dict[tuple[str, str], str] = {}
    entity_boosted: set[str] = set()
    support_paths: list[ExpandedPath] = []
    seen_support_paths: set[tuple] = set()
    parsed_entities = {entity.lower() for entity in parsed.entities}

    _expand_requested_relationships(
        conn,
        candidates,
        parsed,
        seen,
        expanded_nodes,
        edge_facts,
        support_paths,
        seen_support_paths,
    )

    for node in candidates:
        edges_out = get_edges_from(conn, node.id, relation="REFERS_TO")
        for edge in _weighted_edges(edges_out):

            target = get_node(conn, edge.target_id)
            if target is None or target.type != "entity":
                continue

            if target.title.lower() in parsed_entities:
                entity_boosted.add(node.id)

            if not _is_traversable(target):
                continue

            surface_target = _is_surfaceable(target)
            if surface_target:
                _record_edge_fact(edge_facts, edge.source_id, edge.target_id, edge.fact)

            if surface_target:
                _add_node_if_new(seen, expanded_nodes, target)

            reverse_edges = get_edges_to(conn, target.id, relation="REFERS_TO")
            has_related_support = False
            for reverse_edge in _weighted_edges(reverse_edges):

                related = get_node(conn, reverse_edge.source_id)
                if not _is_surfaceable(related):
                    continue
                if related.id == node.id:
                    continue
                has_related_support = True

                if surface_target:
                    _record_edge_fact(edge_facts, reverse_edge.source_id, reverse_edge.target_id, reverse_edge.fact)
                _add_node_if_new(seen, expanded_nodes, related)
                _record_support_path(
                    support_paths,
                    seen_support_paths,
                    ExpandedPath(
                        kind="shared_entity",
                        anchor_id=node.id,
                        related_id=related.id,
                        bridge_id=target.id,
                        anchor_label=_node_label(node, node.id),
                        related_label=_node_label(related, related.id),
                        bridge_label=_node_label(target, target.id),
                        segments=[
                            _build_path_segment(
                                source_id=edge.source_id,
                                target_id=edge.target_id,
                                relation=edge.relation,
                                fact=edge.fact,
                                source_label=_node_label(node, node.id),
                                target_label=_node_label(target, target.id),
                            ),
                            _build_path_segment(
                                source_id=reverse_edge.source_id,
                                target_id=reverse_edge.target_id,
                                relation=reverse_edge.relation,
                                fact=reverse_edge.fact,
                                source_label=_node_label(related, related.id),
                                target_label=_node_label(target, target.id),
                            ),
                        ],
                        score=(edge.weight + reverse_edge.weight) / 2,
                    ),
                )

            if _should_expand_related_concepts(parsed):
                for entity_edge in _weighted_edges(get_edges_from(conn, target.id, relation="RELATED")):
                    related_entity = get_node(conn, entity_edge.target_id)
                    if related_entity is None or related_entity.type != "entity" or not _is_traversable(related_entity):
                        continue

                    _record_edge_fact(edge_facts, entity_edge.source_id, entity_edge.target_id, entity_edge.fact)
                    related_entity_edges = get_edges_to(conn, related_entity.id, relation="REFERS_TO")
                    has_chain_support = False
                    for related_entity_edge in _weighted_edges(related_entity_edges):
                        related_node = get_node(conn, related_entity_edge.source_id)
                        if not _is_surfaceable(related_node):
                            continue
                        if related_node.id == node.id:
                            continue

                        has_chain_support = True
                        _record_edge_fact(
                            edge_facts,
                            related_entity_edge.source_id,
                            related_entity_edge.target_id,
                            related_entity_edge.fact,
                        )
                        _add_node_if_new(seen, expanded_nodes, related_node)
                        _record_support_path(
                            support_paths,
                            seen_support_paths,
                            ExpandedPath(
                                kind="entity_chain",
                                anchor_id=node.id,
                                related_id=related_node.id,
                                bridge_id=related_entity.id,
                                anchor_label=_node_label(node, node.id),
                                related_label=_node_label(related_node, related_node.id),
                                bridge_label=_node_label(related_entity, related_entity.id),
                                segments=[
                                    _build_path_segment(
                                        source_id=edge.source_id,
                                        target_id=edge.target_id,
                                        relation=edge.relation,
                                        fact=edge.fact,
                                        source_label=_node_label(node, node.id),
                                        target_label=_node_label(target, target.id),
                                    ),
                                    _build_path_segment(
                                        source_id=entity_edge.source_id,
                                        target_id=entity_edge.target_id,
                                        relation=entity_edge.relation,
                                        fact=entity_edge.fact,
                                        source_label=_node_label(target, target.id),
                                        target_label=_node_label(related_entity, related_entity.id),
                                    ),
                                    _build_path_segment(
                                        source_id=related_entity_edge.source_id,
                                        target_id=related_entity_edge.target_id,
                                        relation=related_entity_edge.relation,
                                        fact=related_entity_edge.fact,
                                        source_label=_node_label(related_node, related_node.id),
                                        target_label=_node_label(related_entity, related_entity.id),
                                    ),
                                ],
                                score=(edge.weight + entity_edge.weight + related_entity_edge.weight) / 3,
                            ),
                        )

                    if parsed.question_shape == "gap" and not has_chain_support:
                        _record_support_path(
                            support_paths,
                            seen_support_paths,
                            ExpandedPath(
                                kind="nearby_related_entity",
                                anchor_id=node.id,
                                related_id=node.id,
                                bridge_id=related_entity.id,
                                anchor_label=_node_label(node, node.id),
                                related_label=_node_label(node, node.id),
                                bridge_label=_node_label(related_entity, related_entity.id),
                                segments=[
                                    _build_path_segment(
                                        source_id=edge.source_id,
                                        target_id=edge.target_id,
                                        relation=edge.relation,
                                        fact=edge.fact,
                                        source_label=_node_label(node, node.id),
                                        target_label=_node_label(target, target.id),
                                    ),
                                    _build_path_segment(
                                        source_id=entity_edge.source_id,
                                        target_id=entity_edge.target_id,
                                        relation=entity_edge.relation,
                                        fact=entity_edge.fact,
                                        source_label=_node_label(target, target.id),
                                        target_label=_node_label(related_entity, related_entity.id),
                                    ),
                                ],
                                score=(edge.weight + entity_edge.weight) / 2,
                            ),
                        )

            if parsed.question_shape == "gap" and not has_related_support:
                _record_support_path(
                    support_paths,
                    seen_support_paths,
                    ExpandedPath(
                        kind="nearby_entity",
                        anchor_id=node.id,
                        related_id=node.id,
                        bridge_id=target.id,
                        anchor_label=_node_label(node, node.id),
                        related_label=_node_label(node, node.id),
                        bridge_label=_node_label(target, target.id),
                        segments=[
                            _build_path_segment(
                                source_id=edge.source_id,
                                target_id=edge.target_id,
                                relation=edge.relation,
                                fact=edge.fact,
                                source_label=_node_label(node, node.id),
                                target_label=_node_label(target, target.id),
                            )
                        ],
                        score=edge.weight * 0.8,
                    ),
                )

    for node in candidates:
        if node.type != "note":
            continue

        _expand_outgoing_relation(
            conn,
            node_id=node.id,
            node_label=_node_label(node, node.id),
            relation="DERIVED_FROM",
            seen=seen,
            expanded_nodes=expanded_nodes,
            edge_facts=edge_facts,
            support_paths=support_paths,
            seen_support_paths=seen_support_paths,
        )
        _expand_outgoing_relation(
            conn,
            node_id=node.id,
            node_label=_node_label(node, node.id),
            relation="SUPERSEDES",
            seen=seen,
            expanded_nodes=expanded_nodes,
            edge_facts=edge_facts,
            support_paths=support_paths,
            seen_support_paths=seen_support_paths,
            allow_reference=True,
        )

    if parsed.intent == "reason":
        for node in candidates:
            _expand_outgoing_relation(
                conn,
                node_id=node.id,
                node_label=_node_label(node, node.id),
                relation="RELATED",
                seen=seen,
                expanded_nodes=expanded_nodes,
                edge_facts=edge_facts,
                support_paths=support_paths,
                seen_support_paths=seen_support_paths,
            )

    return ExpandedResult(
        nodes=expanded_nodes,
        edge_facts=edge_facts,
        entity_boosted_ids=entity_boosted,
        support_paths=support_paths,
    )


__all__ = ["ExpandedPath", "ExpandedPathSegment", "ExpandedResult", "expand"]