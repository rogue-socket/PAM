from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
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
class _LineItem:
    """A single output line plus enough metadata to truncate without
    leaving relationship lines pointing at dropped node lines."""

    text: str
    kind: str  # "structural" | "node" | "ref"
    node_id: str | None = None
    refs: frozenset[str] = field(default_factory=frozenset)


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
    node_lookup = {node.id: node for node in all_nodes}
    graph_answer_first = bool(result.graph_explanations)
    relationship_first = result.query_meta.get("answer_mode") == "relationship" and bool(result.relationships)

    items: list[_LineItem] = []
    if graph_answer_first:
        _plan_graph_answer(items, result.graph_explanations)
    elif relationship_first:
        _plan_relationships(items, result.relationships, result.edge_facts, node_lookup)

    _plan_node_section(items, "Events", result.events)
    _plan_node_section(items, "Notes", result.notes)
    _plan_node_section(items, "Sources", result.sources)
    _plan_node_section(items, "Entities", result.entities)
    _plan_conflict_section(items, "Conflicts", result.conflicts, "contradicts", node_lookup)
    _plan_conflict_section(items, "Superseded", result.superseded, "supersedes", node_lookup)
    if not graph_answer_first and not relationship_first:
        _plan_relationships(items, result.relationships, result.edge_facts, node_lookup)

    header = [SECTION_DIVIDER, f"## Retrieved Memories ({len(all_nodes)} results)"]
    full_lines = [*header, *(item.text for item in items), SECTION_DIVIDER]
    rendered = "\n".join(full_lines)
    if len(rendered) <= MAX_CONTEXT_CHARS:
        return rendered

    return _truncate_preserving_refs(items, header)


def _truncate_preserving_refs(items: list[_LineItem], header: list[str]) -> str:
    """Greedy two-pass truncation that preserves the no-dangling-reference
    invariant: a "ref" line is kept only if every node it references has its
    own line in the output. Node lines whose ids are referenced by any
    candidate ref are kept first; remaining nodes fill leftover budget;
    refs are admitted last and skipped if their endpoints aren't present."""
    suffix = [SECTION_DIVIDER, "[truncated]"]
    base = "\n".join([*header, *suffix])
    budget = MAX_CONTEXT_CHARS - len(base)

    referenced_ids: set[str] = set()
    for item in items:
        if item.kind == "ref":
            referenced_ids |= item.refs

    selected: set[int] = set()
    used = 0

    def cost(text: str) -> int:
        return len(text) + 1  # one newline per line

    # Pass 1a: must-keep node lines (referenced by some ref) + structural lines.
    for i, item in enumerate(items):
        if item.kind == "node" and item.node_id in referenced_ids:
            selected.add(i)
            used += cost(item.text)
        elif item.kind == "structural":
            addition = cost(item.text)
            if used + addition <= budget:
                selected.add(i)
                used += addition

    # Pass 1b: remaining node lines, greedily.
    for i, item in enumerate(items):
        if i in selected or item.kind != "node":
            continue
        addition = cost(item.text)
        if used + addition <= budget:
            selected.add(i)
            used += addition

    selected_node_ids = {items[i].node_id for i in selected if items[i].kind == "node"}

    # Pass 2: ref lines whose endpoints are all present.
    for i, item in enumerate(items):
        if item.kind != "ref":
            continue
        if not item.refs.issubset(selected_node_ids):
            continue
        addition = cost(item.text)
        if used + addition <= budget:
            selected.add(i)
            used += addition

    # Drop any structural line that has no body following it before the next
    # structural header (avoids an empty "### Relationships" with no entries).
    selected = _drop_orphaned_section_headers(items, selected)

    output = list(header)
    for i, item in enumerate(items):
        if i in selected:
            output.append(item.text)
    output.extend(suffix)
    return "\n".join(output)


def _drop_orphaned_section_headers(items: list[_LineItem], selected: set[int]) -> set[int]:
    """Remove a section header (e.g. '### Relationships') if no node/ref
    line under it survived selection. Keeps blanks/dividers intact."""
    kept = set(selected)
    n = len(items)
    for i, item in enumerate(items):
        if i not in kept or item.kind != "structural":
            continue
        if not item.text.startswith("### "):
            continue
        has_content = False
        for j in range(i + 1, n):
            other = items[j]
            if other.kind == "structural" and other.text.startswith("### "):
                break
            if j in kept and other.kind in ("node", "ref"):
                has_content = True
                break
        if not has_content:
            kept.discard(i)
    return kept


def _plan_graph_answer(items: list[_LineItem], explanations: Iterable[GraphExplanation]) -> None:
    materialized = list(explanations)
    if not materialized:
        return

    items.append(_LineItem(text="", kind="structural"))
    items.append(_LineItem(text="### Graph Answer", kind="structural"))
    for explanation in materialized:
        items.append(
            _LineItem(
                text=f"- {explanation.title}: {explanation.summary}",
                kind="ref",
                refs=frozenset(explanation.node_ids),
            )
        )


def _plan_node_section(items: list[_LineItem], title: str, nodes: Iterable[Node]) -> None:
    materialized = list(nodes)
    if not materialized:
        return

    items.append(_LineItem(text="", kind="structural"))
    items.append(_LineItem(text=f"### {title}", kind="structural"))
    for node in materialized:
        items.append(
            _LineItem(text=f"- {_format_node_line(node)}", kind="node", node_id=node.id)
        )


def _plan_conflict_section(
    items: list[_LineItem],
    title: str,
    pairs: Iterable[tuple[str, str]],
    verb: str,
    node_lookup: dict[str, Node],
) -> None:
    materialized = list(pairs)
    if not materialized:
        return

    items.append(_LineItem(text="", kind="structural"))
    items.append(_LineItem(text=f"### {title}", kind="structural"))
    for left_id, right_id in materialized:
        items.append(
            _LineItem(
                text=f"- \"{_node_label(left_id, node_lookup)}\" {verb} \"{_node_label(right_id, node_lookup)}\"",
                kind="ref",
                refs=frozenset({left_id, right_id}),
            )
        )


def _plan_relationships(
    items: list[_LineItem],
    relationships: list[Edge],
    edge_facts: dict[tuple[str, str], str],
    node_lookup: dict[str, Node],
) -> None:
    if not relationships and not edge_facts:
        return

    items.append(_LineItem(text="", kind="structural"))
    items.append(_LineItem(text="### Relationships", kind="structural"))
    if relationships:
        for edge in relationships:
            fact = edge.fact.strip() or edge_facts.get((edge.source_id, edge.target_id), "").strip()
            if fact:
                text = (
                    f'- "{_node_label(edge.source_id, node_lookup)}" {edge.relation}'
                    f' "{_node_label(edge.target_id, node_lookup)}" - "{fact}"'
                )
            else:
                text = (
                    f'- "{_node_label(edge.source_id, node_lookup)}" {edge.relation}'
                    f' "{_node_label(edge.target_id, node_lookup)}"'
                )
            items.append(
                _LineItem(text=text, kind="ref", refs=frozenset({edge.source_id, edge.target_id}))
            )
        return

    for (source_id, target_id), fact in edge_facts.items():
        if fact:
            text = (
                f"- \"{_node_label(source_id, node_lookup)}\" RELATED"
                f" \"{_node_label(target_id, node_lookup)}\" - \"{fact.strip()}\""
            )
        else:
            text = (
                f"- \"{_node_label(source_id, node_lookup)}\" RELATED"
                f" \"{_node_label(target_id, node_lookup)}\""
            )
        items.append(
            _LineItem(text=text, kind="ref", refs=frozenset({source_id, target_id}))
        )


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