from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from pam.db.edges import Edge
from pam.db.nodes import Node
from pam.ingestion.pipeline import ingest
from pam.retrieval.ranker import GraphExplanation, RetrievalResult
from pam.retrieval.search import retrieve


MAX_CONTEXT_CHARS = 4000
SECTION_DIVIDER = "---"


@dataclass
class AgentIngestResult:
    node_id: str


def _looks_like_link(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https", "file"}


def _ingest_kwargs_for_agent(
    raw_value: str,
    *,
    normalized_kind: str,
    session_id: str | None,
    valid_at: datetime | None,
    workspace_id: str | Path | None,
    parent_note_id: str | None,
) -> dict[str, object]:
    base_kwargs: dict[str, object] = {
        "session_id": session_id,
        "provided_at": valid_at,
        "workspace_id": workspace_id,
    }

    if normalized_kind == "source":
        return {
            **base_kwargs,
            "input_type": "document",
            "node_type": "source",
            "parent_note_id": parent_note_id,
        }
    if normalized_kind == "event":
        return {
            **base_kwargs,
            "input_type": "task",
            "node_type": "event",
        }
    if normalized_kind in {"", "link"} and _looks_like_link(raw_value):
        return {
            **base_kwargs,
            "input_type": "link",
            "url": raw_value,
            "parent_note_id": parent_note_id,
        }
    return {
        **base_kwargs,
        "input_type": "note",
        "node_type": "note",
    }


def ingest_for_agent(
    raw_value: str,
    *,
    kind: str | None = None,
    session_id: str | None = None,
    valid_at: datetime | None = None,
    workspace_id: str | Path | None = None,
    parent_note_id: str | None = None,
) -> AgentIngestResult:
    normalized_kind = (kind or "").strip().lower()
    node_id = ingest(
        raw_value,
        **_ingest_kwargs_for_agent(
            raw_value,
            normalized_kind=normalized_kind,
            session_id=session_id,
            valid_at=valid_at,
            workspace_id=workspace_id,
            parent_note_id=parent_note_id,
        ),
    )
    return AgentIngestResult(node_id=node_id)


def query_for_agent(raw_query: str, top_k: int | None = None, workspace_id: str | Path | None = None) -> RetrievalResult:
    """Run the retrieval pipeline through a stable agent-facing entrypoint."""
    kwargs = {"top_k": top_k}
    if workspace_id is not None:
        kwargs["workspace_id"] = str(workspace_id)
    return retrieve(raw_query, **kwargs)


# This formatter favors dense, predictable context-window packing for agents.
# Do not merge it with CLI or eval rendering unless those output contracts align.
def format_for_context_window(result: RetrievalResult) -> str:
    """Render retrieved memories into a compact context block for coding agents."""
    all_nodes = [*result.events, *result.notes, *result.sources, *result.entities]
    lines = [SECTION_DIVIDER, f"## Retrieved Memories ({len(all_nodes)} results)"]
    node_lookup = {node.id: node for node in all_nodes}
    graph_answer_first = bool(result.graph_explanations)
    relationship_first = result.query_meta.get("answer_mode") == "relationship" and bool(result.relationships)

    if graph_answer_first:
        _append_graph_answer(lines, result.graph_explanations)
    elif relationship_first:
        _append_relationships(lines, result.relationships, result.edge_facts, node_lookup)

    _append_node_section(lines, "Events", result.events)
    _append_node_section(lines, "Notes", result.notes)
    _append_node_section(lines, "Sources", result.sources)
    _append_node_section(lines, "Entities", result.entities)
    _append_conflict_section(lines, "Conflicts", result.conflicts, "contradicts", node_lookup)
    _append_conflict_section(lines, "Superseded", result.superseded, "supersedes", node_lookup)
    if not graph_answer_first and not relationship_first:
        _append_relationships(lines, result.relationships, result.edge_facts, node_lookup)
    lines.append(SECTION_DIVIDER)

    rendered = "\n".join(lines)
    if len(rendered) <= MAX_CONTEXT_CHARS:
        return rendered

    truncated_lines = [SECTION_DIVIDER, f"## Retrieved Memories ({len(all_nodes)} results)"]
    budget = MAX_CONTEXT_CHARS - len(SECTION_DIVIDER) - len("\n[truncated]") - 1
    for line in lines[2:-1]:
        if len("\n".join([*truncated_lines, line, SECTION_DIVIDER, "[truncated]"])) > budget:
            break
        truncated_lines.append(line)
    truncated_lines.extend([SECTION_DIVIDER, "[truncated]"])
    return "\n".join(truncated_lines)


def _append_graph_answer(lines: list[str], explanations: Iterable[GraphExplanation]) -> None:
    materialized = list(explanations)
    if not materialized:
        return

    lines.append("")
    lines.append("### Graph Answer")
    for explanation in materialized:
        lines.append(f"- {explanation.title}: {explanation.summary}")


def _append_node_section(lines: list[str], title: str, nodes: Iterable[Node]) -> None:
    materialized = list(nodes)
    if not materialized:
        return

    lines.append("")
    lines.append(f"### {title}")
    for node in materialized:
        lines.append(f"- {_format_node_line(node)}")


def _append_conflict_section(
    lines: list[str],
    title: str,
    pairs: Iterable[tuple[str, str]],
    verb: str,
    node_lookup: dict[str, Node],
) -> None:
    materialized = list(pairs)
    if not materialized:
        return

    lines.append("")
    lines.append(f"### {title}")
    for left_id, right_id in materialized:
        lines.append(f"- \"{_node_label(left_id, node_lookup)}\" {verb} \"{_node_label(right_id, node_lookup)}\"")


def _append_relationships(
    lines: list[str],
    relationships: list[Edge],
    edge_facts: dict[tuple[str, str], str],
    node_lookup: dict[str, Node],
) -> None:
    if not relationships and not edge_facts:
        return

    lines.append("")
    lines.append("### Relationships")
    if relationships:
        for edge in relationships:
            fact = edge.fact.strip() or edge_facts.get((edge.source_id, edge.target_id), "").strip()
            if fact:
                lines.append(
                    f'- "{_node_label(edge.source_id, node_lookup)}" {edge.relation} "{_node_label(edge.target_id, node_lookup)}" - "{fact}"'
                )
            else:
                lines.append(
                    f'- "{_node_label(edge.source_id, node_lookup)}" {edge.relation} "{_node_label(edge.target_id, node_lookup)}"'
                )
        return

    for (source_id, target_id), fact in edge_facts.items():
        if fact:
            lines.append(
                f"- \"{_node_label(source_id, node_lookup)}\" RELATED \"{_node_label(target_id, node_lookup)}\" - \"{fact.strip()}\""
            )
        else:
            lines.append(f"- \"{_node_label(source_id, node_lookup)}\" RELATED \"{_node_label(target_id, node_lookup)}\"")


def _format_node_line(node: Node) -> str:
    valid_at = node.valid_at.date().isoformat()
    label = node.summary.strip() if node.summary.strip() else _truncate(node.content.strip(), 100)
    if not label:
        label = node.title.strip() or node.id

    if node.type == "source":
        source_ref = (node.metadata or {}).get("url") or node.title
        return f"[{source_ref}] ({valid_at}) - {label}"

    return f"[{node.title}] ({valid_at}) - {label}"


def _node_label(node_id: str, node_lookup: dict[str, Node]) -> str:
    node = node_lookup.get(node_id)
    if node is None:
        return node_id[:8]
    return node.title or node.summary or node.id[:8]


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


__all__ = ["AgentIngestResult", "format_for_context_window", "ingest_for_agent", "query_for_agent"]