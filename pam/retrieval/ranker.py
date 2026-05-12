from __future__ import annotations

import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from math import exp
from typing import Any

from config import (
    DERIVED_PROPAGATION_ALPHA,
    DERIVED_PROPAGATION_SEED_FLOOR,
    DERIVED_PROPAGATION_SINK_CEILING,
    ENTITY_BOOST_SCORE,
    RELATIONSHIP_PRIORITY_BONUS,
    TOP_K,
    WEIGHT_IMPORTANCE,
    WEIGHT_RECENCY,
    WEIGHT_TEXT_RELEVANCE,
    WEIGHT_VEC_SIMILARITY,
)
from pam.db.edges import Edge, get_edges_between
from pam.db.nodes import Node, increment_access_count
from pam.db.schema import utcnow
from pam.retrieval.graph_expander import ExpandedPath, ExpandedPathSegment, ExpandedResult
from pam.retrieval.query_parser import ParsedQuery


@dataclass
class RetrievalResult:
    events: list[Node]
    entities: list[Node]
    notes: list[Node]
    sources: list[Node]
    conflicts: list[tuple[str, str]]
    superseded: list[tuple[str, str]]
    edge_facts: dict[tuple[str, str], str]
    session_groups: dict[str, list[str]]
    query_meta: dict[str, Any]
    ordered_nodes: list[Node] = field(default_factory=list)
    relationships: list[Edge] = field(default_factory=list)
    graph_explanations: list["GraphExplanation"] = field(default_factory=list)
    score_components: dict[str, dict[str, float]] = field(default_factory=dict)


@dataclass
class GraphPathSegment:
    source_id: str
    target_id: str
    relation: str
    fact: str = ""
    source_label: str = ""
    target_label: str = ""


@dataclass
class GraphExplanation:
    kind: str
    title: str
    summary: str
    node_ids: list[str] = field(default_factory=list)
    path: list[GraphPathSegment] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def days_since(dt, now) -> float:
    return max((now - dt).total_seconds() / 86400.0, 0.0)


def score(
    node: Node,
    fts_rank: float | None,
    entity_boost: bool,
    now,
    vector_similarity: float | None = None,
) -> tuple[float, dict[str, float]]:
    """Return (total, components). Components are post-weight contributions
    that sum to total exactly under the same float arithmetic, so callers
    can attribute a node's rank to specific signals without re-deriving
    weights."""
    if fts_rank is not None:
        text_relevance = abs(fts_rank) / (1.0 + abs(fts_rank))
    else:
        text_relevance = 0.0

    recency = exp(-0.01 * days_since(node.valid_at, now))
    importance = node.importance
    entity_bonus = ENTITY_BOOST_SCORE if entity_boost else 0.0
    vec_sim = max(0.0, vector_similarity) if vector_similarity is not None else 0.0

    components = {
        "text_relevance": WEIGHT_TEXT_RELEVANCE * text_relevance,
        "vector_similarity": WEIGHT_VEC_SIMILARITY * vec_sim,
        "recency": WEIGHT_RECENCY * recency,
        "importance": WEIGHT_IMPORTANCE * importance,
        "entity_bonus": entity_bonus,
    }
    total = (
        components["text_relevance"]
        + components["vector_similarity"]
        + components["recency"]
        + components["importance"]
        + components["entity_bonus"]
    )
    return total, components


def _edge_matches_requested_direction(edge: Edge, anchor_ids: set[str], relation_direction: str | None) -> bool:
    if not anchor_ids:
        return True
    if relation_direction == "incoming":
        return edge.target_id in anchor_ids
    if relation_direction == "outgoing":
        return edge.source_id in anchor_ids
    return edge.source_id in anchor_ids or edge.target_id in anchor_ids


def _score_relationship(edge: Edge, node_scores: dict[str, float], *, direction_match: bool) -> float:
    relationship_score = edge.weight
    relationship_score += node_scores.get(edge.source_id, 0.0)
    relationship_score += node_scores.get(edge.target_id, 0.0)
    if edge.fact.strip():
        relationship_score += 0.1
    if direction_match:
        relationship_score += 0.35
    return relationship_score


def _rank_relationship_hits(
    inter_edges: list[Edge],
    parsed: ParsedQuery,
    anchor_ids: set[str],
    node_scores: dict[str, float],
) -> list[Edge]:
    if not parsed.relation_filters:
        return []

    requested_relations = set(parsed.relation_filters)
    filtered_edges = [edge for edge in inter_edges if edge.relation in requested_relations]
    if not filtered_edges:
        return []

    # Direction match is a +0.35 sort bonus in _score_relationship rather than
    # a hard filter: dropping non-directional edges loses graph-expanded
    # targets that aren't in candidate_ids (e.g. detailed-relationship idx 81's
    # seed -> derived-source edge, where the derived source reaches the pool
    # via graph expansion, not via FTS/vec).
    return sorted(
        filtered_edges,
        key=lambda edge: _score_relationship(
            edge,
            node_scores,
            direction_match=_edge_matches_requested_direction(edge, anchor_ids, parsed.relation_direction),
        ),
        reverse=True,
    )


def _prioritized_relationship_node_ids(relationships: list[Edge], relation_direction: str | None) -> list[str]:
    ordered_ids: list[str] = []
    seen: set[str] = set()

    for edge in relationships:
        if relation_direction == "outgoing":
            candidate_ids = [edge.target_id, edge.source_id]
        else:
            candidate_ids = [edge.source_id, edge.target_id]

        for node_id in candidate_ids:
            if node_id in seen:
                continue
            seen.add(node_id)
            ordered_ids.append(node_id)

    return ordered_ids


def _relationship_result_nodes(
    combined: dict[str, tuple[Node, float | None]],
    scored_items: list[tuple[Node, float]],
    relationships: list[Edge],
    relation_direction: str | None,
    *,
    limit: int,
) -> list[Node]:
    prioritized_ids = _prioritized_relationship_node_ids(relationships, relation_direction)
    target_node_count = max(limit, len(prioritized_ids))
    seen_node_ids = set(prioritized_ids)
    top_nodes = [combined[node_id][0] for node_id in prioritized_ids if node_id in combined]

    for node, _ in scored_items:
        if len(top_nodes) >= target_node_count:
            break
        if node.id in seen_node_ids:
            continue
        seen_node_ids.add(node.id)
        top_nodes.append(node)

    return top_nodes


def _score_support_path(path: ExpandedPath, node_scores: dict[str, float], parsed: ParsedQuery) -> float:
    support_score = path.score
    support_score += node_scores.get(path.anchor_id, 0.0)
    support_score += node_scores.get(path.related_id, 0.0)
    if path.bridge_id:
        support_score += 0.2
    if path.kind == "shared_entity" and parsed.question_shape in {"relationship", "theme", "gap", "influence"}:
        support_score += 0.35
    if path.kind == "entity_chain" and parsed.question_shape in {"relationship", "theme", "gap", "influence"}:
        support_score += 0.4
    if parsed.question_shape == "influence" and any(segment.relation == "DERIVED_FROM" for segment in path.segments):
        support_score += 0.35
    return support_score


def _rank_support_paths(
    support_paths: list[ExpandedPath],
    parsed: ParsedQuery,
    node_scores: dict[str, float],
    available_ids: set[str],
) -> list[ExpandedPath]:
    materialized = [
        path
        for path in support_paths
        if path.anchor_id in available_ids and path.related_id in available_ids
    ]
    return sorted(materialized, key=lambda path: _score_support_path(path, node_scores, parsed), reverse=True)


def _support_path_result_nodes(
    combined: dict[str, tuple[Node, float | None]],
    scored_items: list[tuple[Node, float]],
    support_paths: list[ExpandedPath],
    node_scores: dict[str, float],
    *,
    limit: int,
) -> list[Node]:
    # Same shape as _relationship_result_nodes: score-sort with a bonus for
    # support-path endpoints, rather than path-iteration order which bypassed
    # node_scores and buried high-scoring gold past `limit`.
    prioritized_ids: set[str] = set()
    for path in support_paths:
        for node_id in (path.anchor_id, path.related_id):
            if node_id in combined:
                prioritized_ids.add(node_id)

    def keyfn(item: tuple[Node, float]) -> float:
        node, _ = item
        score = node_scores.get(node.id, 0.0)
        if node.id in prioritized_ids:
            score += RELATIONSHIP_PRIORITY_BONUS
        return score

    sorted_items = sorted(scored_items, key=keyfn, reverse=True)
    target_node_count = max(limit, len(prioritized_ids))
    return [node for node, _ in sorted_items[:target_node_count]]


def _session_groups(nodes: list[Node]) -> dict[str, list[str]]:
    session_groups: dict[str, list[str]] = {}
    for node in nodes:
        if node.session_id:
            session_groups.setdefault(node.session_id, []).append(node.id)
    return session_groups


def _query_meta(parsed: ParsedQuery) -> dict[str, Any]:
    return {
        "keywords": parsed.keywords,
        "entities": parsed.entities,
        "time_range": parsed.time_range,
        "intent": parsed.intent,
        "relation_filters": parsed.relation_filters,
        "relation_direction": parsed.relation_direction,
        "answer_mode": parsed.answer_mode,
        "question_shape": parsed.question_shape,
        "anchor_terms": parsed.anchor_terms,
    }


def _partition_nodes(nodes: list[Node]) -> dict[str, list[Node]]:
    return {
        "event": [node for node in nodes if node.type == "event"],
        "entity": [node for node in nodes if node.type == "entity"],
        "note": [node for node in nodes if node.type == "note"],
        "source": [node for node in nodes if node.type == "source"],
    }


def _graph_node_label(node_id: str, node_lookup: dict[str, Node]) -> str:
    node = node_lookup.get(node_id)
    if node is None:
        return node_id[:8]

    for candidate in (node.title.strip(), node.summary.strip()):
        if candidate:
            return candidate
    return node.id[:8]


def _graph_node_label_with_fallback(node_id: str, label: str, node_lookup: dict[str, Node]) -> str:
    if label.strip():
        return label.strip()
    return _graph_node_label(node_id, node_lookup)


def _graph_edge_fact(edge: Edge, edge_facts: dict[tuple[str, str], str]) -> str:
    fact = edge.fact.strip()
    if fact:
        return fact
    return edge_facts.get((edge.source_id, edge.target_id), "").strip()


def _graph_edge_summary(
    source_id: str,
    target_id: str,
    relation: str,
    node_lookup: dict[str, Node],
    fact: str = "",
) -> str:
    summary = f'"{_graph_node_label(source_id, node_lookup)}" {relation} "{_graph_node_label(target_id, node_lookup)}"'
    if fact:
        return f'{summary} - "{fact}"'
    return summary


def _graph_segment_from_expanded(segment: ExpandedPathSegment) -> GraphPathSegment:
    return GraphPathSegment(
        source_id=segment.source_id,
        target_id=segment.target_id,
        relation=segment.relation,
        fact=segment.fact,
        source_label=segment.source_label,
        target_label=segment.target_label,
    )


def _graph_explanation_title(question_shape: str, relation: str) -> str:
    if question_shape == "evolution" or relation == "SUPERSEDES":
        return "Evolution path"
    if question_shape == "influence" or relation == "DERIVED_FROM":
        return "Influence path"
    if question_shape == "theme" or relation == "RELATED":
        return "Theme connection"
    if question_shape == "gap":
        return "Nearby evidence"
    if relation == "CONTRADICTS":
        return "Conflict edge"
    if relation == "REFERS_TO":
        return "Reference path"
    return "Relationship hit"


def _cluster_title(question_shape: str) -> str:
    return {
        "theme": "Theme cluster",
        "gap": "Coverage frontier",
        "influence": "Influence neighborhood",
        "evolution": "Change neighborhood",
    }.get(question_shape, "Graph neighborhood")


def _cluster_summary(
    top_nodes: list[Node],
    relationships: list[Edge],
    parsed: ParsedQuery,
    support_paths: list[ExpandedPath],
) -> str:
    bridge_counts = Counter(
        path.bridge_label.strip() for path in support_paths if path.bridge_label.strip()
    )
    if parsed.question_shape == "theme" and bridge_counts:
        dominant_bridges = ", ".join(f'"{label}"' for label, _ in bridge_counts.most_common(4))
        return f"Most connected concepts: {dominant_bridges}."
    if parsed.question_shape == "gap" and bridge_counts:
        minimum_support = min(bridge_counts.values())
        nearby = [label for label, count in bridge_counts.items() if count == minimum_support][:4]
        if nearby:
            nearby_text = ", ".join(f'"{label}"' for label in nearby)
            return f"Nearby but thinly connected concepts: {nearby_text}."

    focus_labels = [node.title.strip() or node.id[:8] for node in top_nodes[:3]]
    focus_text = ", ".join(f'"{label}"' for label in focus_labels) if focus_labels else "the retrieved memories"
    dominant_relations = ", ".join(relation for relation, _ in Counter(edge.relation for edge in relationships).most_common(2))

    if dominant_relations:
        return f"Strongest nearby memories: {focus_text}. Dominant relations: {dominant_relations}."
    if parsed.anchor_terms:
        anchor_text = ", ".join(f'"{anchor}"' for anchor in parsed.anchor_terms[:2])
        return f"No explicit supporting edges matched {anchor_text}; showing the closest stored memories instead."
    return f"Strongest nearby memories: {focus_text}. Explicit graph support is sparse."


def _evolution_summary(top_nodes: list[Node]) -> str:
    ordered = sorted(top_nodes, key=lambda node: (node.valid_at, node.created_at, node.id))
    labels = [node.title.strip() or node.id[:8] for node in ordered[:5]]
    return "Observed progression: " + " -> ".join(f'"{label}"' for label in labels) + "."


def _support_path_title(question_shape: str, path: ExpandedPath) -> str:
    if path.kind == "entity_chain":
        return {
            "influence": "Influence chain",
            "theme": "Theme chain",
            "gap": "Coverage frontier",
            "relationship": "Connection path",
        }.get(question_shape, "Connection path")
    if path.kind == "shared_entity":
        return {
            "influence": "Influence bridge",
            "theme": "Theme bridge",
            "gap": "Coverage frontier",
            "relationship": "Connection path",
        }.get(question_shape, "Connection path")
    return _graph_explanation_title(question_shape, path.segments[0].relation if path.segments else "RELATED")


def _support_path_summary(path: ExpandedPath, parsed: ParsedQuery, node_lookup: dict[str, Node]) -> str:
    anchor_label = _graph_node_label_with_fallback(path.anchor_id, path.anchor_label, node_lookup)
    related_label = _graph_node_label_with_fallback(path.related_id, path.related_label, node_lookup)
    bridge_label = path.bridge_label.strip()

    if path.kind == "nearby_related_entity" and bridge_label:
        return f'"{bridge_label}" is conceptually nearby to "{anchor_label}" through an extracted relationship chain.'

    if path.kind == "entity_chain" and len(path.segments) >= 2:
        first_bridge = path.segments[0].target_label.strip() or bridge_label
        second_bridge = path.segments[1].target_label.strip() if len(path.segments) > 1 else bridge_label
        if parsed.question_shape == "influence":
            return f'"{anchor_label}" reaches "{related_label}" through "{first_bridge}" and "{second_bridge}".'
        if parsed.question_shape == "theme":
            return f'"{anchor_label}" and "{related_label}" are connected by the concept chain "{first_bridge}" -> "{second_bridge}".'
        if parsed.question_shape == "gap":
            return f'"{second_bridge}" extends the concept path from "{anchor_label}" but remains lightly explored.'
        return f'"{anchor_label}" connects to "{related_label}" through "{first_bridge}" and "{second_bridge}".'

    if path.kind == "nearby_entity" and bridge_label:
        return f'"{bridge_label}" sits near "{anchor_label}" but is only lightly connected in the retrieved graph.'

    if path.kind == "shared_entity" and bridge_label:
        if parsed.question_shape == "influence":
            return f'"{anchor_label}" is linked to "{related_label}" through the concept "{bridge_label}".'
        if parsed.question_shape == "theme":
            return f'Shared concept "{bridge_label}" links "{anchor_label}" and "{related_label}".'
        if parsed.question_shape == "gap":
            return f'"{bridge_label}" sits near "{anchor_label}" but is only lightly connected in the retrieved graph.'
        return f'"{anchor_label}" and "{related_label}" connect through "{bridge_label}".'

    if path.segments:
        first = path.segments[0]
        fact = first.fact.strip()
        return _graph_edge_summary(
            first.source_id,
            first.target_id,
            first.relation,
            node_lookup,
            fact,
        )
    return f'"{anchor_label}" connects to "{related_label}".'


def _diagnostic_explanation(top_nodes: list[Node], parsed: ParsedQuery) -> GraphExplanation:
    focus = ", ".join(f'"{anchor}"' for anchor in parsed.anchor_terms[:2])
    if not focus:
        node_labels = [node.title.strip() or node.id[:8] for node in top_nodes[:2]]
        focus = ", ".join(f'"{label}"' for label in node_labels) if node_labels else "this query"

    shape_label = {
        "relationship": "relationship",
        "influence": "influence",
        "evolution": "evolution",
        "theme": "theme",
        "gap": "adjacency",
    }.get(parsed.question_shape, "graph")
    return GraphExplanation(
        kind="diagnostic",
        title="Sparse graph evidence",
        summary=f"No explicit {shape_label} edges matched {focus}; showing the strongest memories instead.",
        node_ids=[node.id for node in top_nodes[:3]],
        metadata={
            "question_shape": parsed.question_shape,
            "answer_mode": parsed.answer_mode,
        },
    )


def _build_graph_explanations(
    top_nodes: list[Node],
    relationships: list[Edge],
    conflicts: list[tuple[str, str]],
    superseded: list[tuple[str, str]],
    edge_facts: dict[tuple[str, str], str],
    support_paths: list[ExpandedPath],
    parsed: ParsedQuery,
) -> list[GraphExplanation]:
    node_lookup = {node.id: node for node in top_nodes}
    explanations: list[GraphExplanation] = []
    represented_edges: set[tuple[str, str, str]] = set()
    represented_support_keys: set[tuple] = set()

    if parsed.question_shape in {"theme", "gap"} and top_nodes:
        explanations.append(
            GraphExplanation(
                kind="cluster",
                title=_cluster_title(parsed.question_shape),
                summary=_cluster_summary(top_nodes, relationships, parsed, support_paths),
                node_ids=[node.id for node in top_nodes[:3]],
                metadata={
                    "question_shape": parsed.question_shape,
                    "answer_mode": parsed.answer_mode,
                },
            )
        )

    if parsed.question_shape == "evolution" and len(top_nodes) > 1:
        explanations.insert(
            0,
            GraphExplanation(
                kind="sequence",
                title="Evolution sequence",
                summary=_evolution_summary(top_nodes),
                node_ids=[node.id for node in sorted(top_nodes, key=lambda node: (node.valid_at, node.created_at, node.id))[:5]],
                metadata={"question_shape": parsed.question_shape},
            ),
        )

    for edge in relationships:
        fact = _graph_edge_fact(edge, edge_facts)
        explanations.append(
            GraphExplanation(
                kind="path",
                title=_graph_explanation_title(parsed.question_shape, edge.relation),
                summary=_graph_edge_summary(edge.source_id, edge.target_id, edge.relation, node_lookup, fact),
                node_ids=[edge.source_id, edge.target_id],
                path=[
                    GraphPathSegment(
                        source_id=edge.source_id,
                        target_id=edge.target_id,
                        relation=edge.relation,
                        fact=fact,
                    )
                ],
                metadata={
                    "relation": edge.relation,
                    "weight": edge.weight,
                    "question_shape": parsed.question_shape,
                },
            )
        )
        represented_edges.add((edge.source_id, edge.target_id, edge.relation))

    for path in support_paths:
        if path.segments and len(path.segments) == 1:
            segment = path.segments[0]
            if (segment.source_id, segment.target_id, segment.relation) in represented_edges:
                continue
        support_key = (
            path.kind,
            path.anchor_id,
            path.related_id,
            path.bridge_id,
        )
        if support_key in represented_support_keys:
            continue
        represented_support_keys.add(support_key)
        explanations.append(
            GraphExplanation(
                kind="path",
                title=_support_path_title(parsed.question_shape, path),
                summary=_support_path_summary(path, parsed, node_lookup),
                node_ids=[node_id for node_id in (path.anchor_id, path.related_id) if node_id],
                path=[_graph_segment_from_expanded(segment) for segment in path.segments],
                metadata={
                    "kind": path.kind,
                    "bridge_id": path.bridge_id,
                    "bridge_label": path.bridge_label,
                    "question_shape": parsed.question_shape,
                },
            )
        )

    for source_id, target_id in conflicts:
        if (source_id, target_id, "CONTRADICTS") in represented_edges:
            continue
        fact = edge_facts.get((source_id, target_id), "").strip()
        explanations.append(
            GraphExplanation(
                kind="conflict",
                title="Conflict edge",
                summary=_graph_edge_summary(source_id, target_id, "CONTRADICTS", node_lookup, fact),
                node_ids=[source_id, target_id],
                path=[GraphPathSegment(source_id=source_id, target_id=target_id, relation="CONTRADICTS", fact=fact)],
            )
        )

    for source_id, target_id in superseded:
        if (source_id, target_id, "SUPERSEDES") in represented_edges:
            continue
        fact = edge_facts.get((source_id, target_id), "").strip()
        explanations.append(
            GraphExplanation(
                kind="path",
                title="Evolution path",
                summary=_graph_edge_summary(source_id, target_id, "SUPERSEDES", node_lookup, fact),
                node_ids=[source_id, target_id],
                path=[GraphPathSegment(source_id=source_id, target_id=target_id, relation="SUPERSEDES", fact=fact)],
            )
        )

    if (
        not explanations
        and not relationships
        and not conflicts
        and not superseded
        and parsed.question_shape in {"relationship", "influence", "evolution"}
        and top_nodes
    ):
        explanations.insert(0, _diagnostic_explanation(top_nodes, parsed))
    elif not explanations and len(top_nodes) > 1:
        explanations.append(
            GraphExplanation(
                kind="cluster",
                title="Graph neighborhood",
                summary=_cluster_summary(top_nodes, relationships, parsed, support_paths),
                node_ids=[node.id for node in top_nodes[:3]],
                metadata={
                    "question_shape": parsed.question_shape,
                    "answer_mode": parsed.answer_mode,
                },
            )
        )

    return explanations


def _propagate_along_derived_from(
    inter_edges: list[Edge],
    node_scores: dict[str, float],
    score_components: dict[str, dict[str, float]],
) -> None:
    # When a DERIVED_FROM edge connects an FTS-anchored seed to a target with
    # near-zero text relevance, transfer a fraction of the seed's text
    # contribution to the target. Models the case where the gold's relevance
    # is the typed graph edge itself rather than any shared keywords.
    for edge in inter_edges:
        if edge.relation != "DERIVED_FROM":
            continue
        seed_text = score_components.get(edge.source_id, {}).get("text_relevance", 0.0)
        target_text = score_components.get(edge.target_id, {}).get("text_relevance", 0.0)
        if seed_text < DERIVED_PROPAGATION_SEED_FLOOR:
            continue
        if target_text > DERIVED_PROPAGATION_SINK_CEILING:
            continue
        boost = DERIVED_PROPAGATION_ALPHA * seed_text
        node_scores[edge.target_id] = node_scores.get(edge.target_id, 0.0) + boost
        score_components.setdefault(edge.target_id, {})["derived_propagation"] = (
            score_components.get(edge.target_id, {}).get("derived_propagation", 0.0) + boost
        )


def rank_and_assemble(
    conn: sqlite3.Connection,
    candidates: list[tuple[Node, float]],
    expanded: ExpandedResult,
    parsed: ParsedQuery,
    top_k: int | None = None,
    vector_similarities: dict[str, float] | None = None,
) -> RetrievalResult:
    now = utcnow()
    combined: dict[str, tuple[Node, float | None]] = {node.id: (node, fts_rank) for node, fts_rank in candidates}

    for node in expanded.nodes:
        combined.setdefault(node.id, (node, None))

    vector_similarities = vector_similarities or {}
    node_scores: dict[str, float] = {}
    score_components: dict[str, dict[str, float]] = {}
    for node, fts_rank in combined.values():
        total, components = score(
            node,
            fts_rank,
            node.id in expanded.entity_boosted_ids,
            now,
            vector_similarity=vector_similarities.get(node.id),
        )
        node_scores[node.id] = total
        score_components[node.id] = components
    limit = top_k or TOP_K
    combined_ids = list(combined)
    combined_id_set = set(combined_ids)
    candidate_ids = {node.id for node, _ in candidates}
    combined_inter_edges = get_edges_between(conn, combined_ids)

    _propagate_along_derived_from(combined_inter_edges, node_scores, score_components)
    scored_items = [(node, node_scores[node.id]) for node, _ in combined.values()]
    scored_items.sort(key=lambda item: item[1], reverse=True)

    if parsed.answer_mode == "relationship":
        ranked_relationships = _rank_relationship_hits(combined_inter_edges, parsed, candidate_ids, node_scores)
        ranked_support_paths = _rank_support_paths(expanded.support_paths, parsed, node_scores, combined_id_set)
        if ranked_relationships:
            relationship_limit = max(1, limit // 2) if limit > 1 else 1
            relationships = ranked_relationships[:relationship_limit]
            top_nodes = _relationship_result_nodes(
                combined,
                scored_items,
                relationships,
                parsed.relation_direction,
                limit=limit,
            )
        elif ranked_support_paths:
            relationships = []
            top_nodes = _support_path_result_nodes(
                combined,
                scored_items,
                ranked_support_paths,
                node_scores,
                limit=limit,
            )
            expanded.support_paths = ranked_support_paths
        else:
            relationships = []
            top_nodes = [node for node, _ in scored_items[:limit]]
    else:
        relationships = []
        top_nodes = [node for node, _ in scored_items[:limit]]

    for node in top_nodes:
        increment_access_count(conn, node.id)

    result_ids = [node.id for node in top_nodes]
    inter_edges = get_edges_between(conn, result_ids)
    conflicts = [(edge.source_id, edge.target_id) for edge in inter_edges if edge.relation == "CONTRADICTS"]
    superseded = [(edge.source_id, edge.target_id) for edge in inter_edges if edge.relation == "SUPERSEDES"]
    if parsed.answer_mode != "relationship" or not parsed.relation_filters:
        relationships = inter_edges

    grouped_nodes = _partition_nodes(top_nodes)
    relevant_support_paths = [
        path
        for path in expanded.support_paths
        if path.anchor_id in result_ids and path.related_id in result_ids
    ]
    graph_explanations = _build_graph_explanations(
        top_nodes,
        relationships,
        conflicts,
        superseded,
        expanded.edge_facts,
        relevant_support_paths,
        parsed,
    )

    return RetrievalResult(
        events=grouped_nodes["event"],
        entities=grouped_nodes["entity"],
        notes=grouped_nodes["note"],
        sources=grouped_nodes["source"],
        conflicts=conflicts,
        superseded=superseded,
        edge_facts=expanded.edge_facts,
        session_groups=_session_groups(top_nodes),
        query_meta=_query_meta(parsed),
        ordered_nodes=top_nodes,
        relationships=relationships,
        graph_explanations=graph_explanations,
        score_components={node.id: score_components[node.id] for node in top_nodes},
    )


__all__ = [
    "GraphExplanation",
    "GraphPathSegment",
    "RetrievalResult",
    "days_since",
    "rank_and_assemble",
    "score",
]