from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import click

from pam.chat_agent import DEFAULT_CHAT_MODEL, ChatAgentError, ChatResponse, answer_with_pam
from pam.db.edges import get_edges_from, get_edges_to
from pam.db.nodes import Node, get_node, list_nodes
from pam.db.fts import rebuild_fts
from pam.db.schema import datetime_to_iso, doctor_report, get_connection, initialize
from pam.embeddings import EmbeddingsUnavailable, backfill_embeddings
from pam.feedback import downvote, pin, supersede, upvote
from pam.ingestion.pipeline import ingest
from pam.lifecycle import apply_decay, unarchive
from pam.retrieval.ranker import GraphExplanation, GraphPathSegment, RetrievalResult
from pam.retrieval.search import retrieve


def parse_datetime(value: str) -> datetime:
    """Parse YYYY-MM-DD or ISO8601 input and normalize to UTC."""
    text = (value or "").strip()
    if not text:
        raise click.BadParameter("datetime value cannot be empty")

    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise click.BadParameter("expected ISO8601 or YYYY-MM-DD") from exc

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


# Keep CLI shaping local to this module. Agent prompts and eval prompts
# intentionally use separate renderers with different stability and size goals.
def _node_to_dict(node: Node) -> dict:
    return {
        "id": node.id,
        "type": node.type,
        "title": node.title,
        "content": node.content,
        "summary": node.summary,
        "content_hash": node.content_hash,
        "created_at": datetime_to_iso(node.created_at),
        "valid_at": datetime_to_iso(node.valid_at),
        "updated_at": datetime_to_iso(node.updated_at),
        "tags": node.tags,
        "session_id": node.session_id,
        "importance": node.importance,
        "access_count": node.access_count,
        "status": node.status,
        "metadata": node.metadata,
    }


def _json_dump(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True)


def _node_summary_label(node: Node, *, limit: int = 80) -> str:
    label = (node.summary or node.title).strip()
    if len(label) <= limit:
        return label
    return label[: max(0, limit - 3)].rstrip() + "..."


def _graph_path_segment_to_dict(segment: GraphPathSegment) -> dict:
    return {
        "source_id": segment.source_id,
        "target_id": segment.target_id,
        "relation": segment.relation,
        "fact": segment.fact,
        "source_label": segment.source_label,
        "target_label": segment.target_label,
    }


def _graph_explanation_to_dict(explanation: GraphExplanation) -> dict:
    return {
        "kind": explanation.kind,
        "title": explanation.title,
        "summary": explanation.summary,
        "node_ids": explanation.node_ids,
        "path": [_graph_path_segment_to_dict(segment) for segment in explanation.path],
        "metadata": explanation.metadata,
    }


def _result_to_dict(result: RetrievalResult) -> dict:
    return {
        "events": [_node_to_dict(node) for node in result.events],
        "entities": [_node_to_dict(node) for node in result.entities],
        "notes": [_node_to_dict(node) for node in result.notes],
        "sources": [_node_to_dict(node) for node in result.sources],
        "relationships": [
            {
                "source_id": edge.source_id,
                "target_id": edge.target_id,
                "relation": edge.relation,
                "weight": edge.weight,
                "fact": edge.fact,
                "created_at": datetime_to_iso(edge.created_at),
            }
            for edge in result.relationships
        ],
        "conflicts": [{"source_id": source_id, "target_id": target_id} for source_id, target_id in result.conflicts],
        "superseded": [{"source_id": source_id, "target_id": target_id} for source_id, target_id in result.superseded],
        "edge_facts": [
            {"source_id": source_id, "target_id": target_id, "fact": fact}
            for (source_id, target_id), fact in result.edge_facts.items()
        ],
        "graph_explanations": [_graph_explanation_to_dict(explanation) for explanation in result.graph_explanations],
        "session_groups": result.session_groups,
        "query_meta": result.query_meta,
        "ordered_nodes": [_node_to_dict(node) for node in result.ordered_nodes],
        "score_components": result.score_components,
    }


def format_node_json(node: Node) -> str:
    return _json_dump(_node_to_dict(node))


def format_nodes_json(nodes: list[Node]) -> str:
    return _json_dump([_node_to_dict(node) for node in nodes])


def format_result_json(result: RetrievalResult) -> str:
    return _json_dump(_result_to_dict(result))


def format_node_human(node: Node) -> None:
    click.echo(f"ID:           {node.id}")
    click.echo(f"Type:         {node.type}")
    click.echo(f"Title:        {node.title}")
    click.echo(f"Status:       {node.status}")
    click.echo(f"Importance:   {node.importance:.2f}")
    click.echo(f"Valid at:     {datetime_to_iso(node.valid_at)}")
    click.echo(f"Created at:   {datetime_to_iso(node.created_at)}")
    click.echo(f"Updated at:   {datetime_to_iso(node.updated_at)}")
    click.echo(f"Tags:         {', '.join(node.tags) if node.tags else '(none)'}")
    click.echo(f"Access count: {node.access_count}")
    if node.session_id:
        click.echo(f"Session:      {node.session_id}")
    if node.metadata:
        click.echo(f"Metadata:     {json.dumps(node.metadata, ensure_ascii=True, sort_keys=True)}")
    if node.summary:
        click.echo(f"\nSummary: {node.summary}")
    if node.content:
        click.echo(f"\nContent:\n{node.content}")


def format_node_summary(node: Node) -> None:
    label = _node_summary_label(node)
    click.echo(f"  {node.id[:8]}  {node.type:8s}  {node.valid_at.date().isoformat()}  {label}")


def _node_label_for_graph(node_id: str, node_lookup: dict[str, Node], explicit_label: str = "") -> str:
    if explicit_label.strip():
        return explicit_label.strip()
    node = node_lookup.get(node_id)
    if node is None:
        return node_id[:8]
    return (node.title or node.summary or node.id[:8]).strip()


def format_result_human(result: RetrievalResult) -> None:
    all_nodes = [*result.events, *result.notes, *result.sources, *result.entities]
    if not all_nodes:
        click.echo("No results found.")
        return

    if result.graph_explanations:
        click.echo("Graph answer:\n")
        node_lookup = {node.id: node for node in all_nodes}
        for explanation in result.graph_explanations:
            click.echo(f"  - {explanation.title}: {explanation.summary}")
            if len(explanation.path) > 1:
                for segment in explanation.path:
                    source_label = _node_label_for_graph(segment.source_id, node_lookup, segment.source_label)
                    target_label = _node_label_for_graph(segment.target_id, node_lookup, segment.target_label)
                    click.echo(f'      "{source_label}" {segment.relation} "{target_label}"')
                    if segment.fact:
                        click.echo(f"        fact: {segment.fact}")
        click.echo("")
    elif result.query_meta.get("answer_mode") == "relationship" and result.relationships:
        click.echo("Relationship hits:\n")
        node_lookup = {node.id: node for node in all_nodes}
        for edge in result.relationships:
            source_label = node_lookup.get(edge.source_id).title if edge.source_id in node_lookup else edge.source_id[:8]
            target_label = node_lookup.get(edge.target_id).title if edge.target_id in node_lookup else edge.target_id[:8]
            click.echo(f'  - "{source_label}" {edge.relation} "{target_label}"')
            if edge.fact:
                click.echo(f"      fact: {edge.fact}")
        click.echo("")

    click.echo(f"Found {len(all_nodes)} result(s):\n")
    for index, node in enumerate(all_nodes, start=1):
        label = _node_summary_label(node)
        click.echo(f"  {index}. [{node.type}] {label}")
        click.echo(f"     ID: {node.id}  |  {node.valid_at.date().isoformat()}  |  importance: {node.importance:.2f}")

    if result.conflicts:
        click.echo("\nConflicts detected:")
        for source_id, target_id in result.conflicts:
            click.echo(f"  {source_id[:8]} <-> {target_id[:8]}")

    if result.superseded:
        click.echo("\nSuperseded nodes in results:")
        for source_id, target_id in result.superseded:
            click.echo(f"  {source_id[:8]} -> {target_id[:8]}")


def _exit_with_error(message: str) -> None:
    click.echo(message, err=True)
    raise click.exceptions.Exit(1)


def _echo_on_success(success: bool, success_message: str, error_message: str) -> None:
    if success:
        click.echo(success_message)
        return
    _exit_with_error(error_message)


def _answer_chat_query(raw_question: str, *, model: str, top_k: int) -> ChatResponse:
    try:
        return answer_with_pam(raw_question, model=model, top_k=top_k, workspace_id=Path.cwd())
    except ChatAgentError as exc:
        _exit_with_error(str(exc))


def _format_graph_edge(conn, edge, *, incoming: bool) -> str:
    related_node = get_node(conn, edge.source_id if incoming else edge.target_id)
    related_label = related_node.title if related_node else (edge.source_id if incoming else edge.target_id)
    fact_suffix = f' - "{edge.fact}"' if edge.fact else ""
    if incoming:
        return f"  <- {edge.relation} <- {related_label} (w={edge.weight:.2f}){fact_suffix}"
    return f"  -> {edge.relation} -> {related_label} (w={edge.weight:.2f}){fact_suffix}"


def _resolve_add_input(text: str | None, url: str | None, filepath: str | None, node_type: str | None) -> tuple[str, str, str | None]:
    provided = [bool(text), bool(url), bool(filepath)]
    if sum(provided) != 1:
        raise click.UsageError("Provide exactly one of text, --url, or --file.")

    if (url or filepath) and node_type is not None:
        raise click.UsageError("--type only applies to plain text input.")

    if filepath:
        return Path(filepath).read_text(encoding="utf-8"), "document", None
    if url:
        return url, "link", url
    return text or "", "note" if node_type == "note" else "task", None


@click.group()
@click.pass_context
def cli(ctx: click.Context) -> None:
    """PAM - Personal Agent Memory."""
    conn = get_connection()
    initialize(conn)
    ctx.ensure_object(dict)
    ctx.obj["conn"] = conn
    ctx.call_on_close(conn.close)


@cli.command()
@click.argument("text", required=False)
@click.option(
    "--type",
    "node_type",
    type=click.Choice(["event", "note"], case_sensitive=False),
    default=None,
    help="Node type. Default: event for plain text, note with --type note.",
)
@click.option("--url", default=None, help="Ingest a URL as a source node.")
@click.option("--file", "filepath", type=click.Path(exists=True, dir_okay=False, path_type=str), default=None, help="Ingest contents of a file.")
@click.option("--session", "session_id", default=None, help="Session UUID to group events.")
@click.option("--at", "valid_at_str", default=None, help="When this happened (ISO8601 or YYYY-MM-DD). Defaults to now.")
@click.option("--force", is_flag=True, help="Suppress session staleness warning.")
@click.pass_context
def add(
    ctx: click.Context,
    text: str | None,
    node_type: str | None,
    url: str | None,
    filepath: str | None,
    session_id: str | None,
    valid_at_str: str | None,
    force: bool,
) -> None:
    """Add a memory to PAM."""
    conn = ctx.obj["conn"]
    raw_text, input_type, resolved_url = _resolve_add_input(text, url, filepath, node_type)
    valid_at = parse_datetime(valid_at_str) if valid_at_str else None

    node_id = ingest(
        raw_text=raw_text,
        input_type=input_type,
        session_id=session_id,
        provided_at=valid_at,
        node_type=(node_type.lower() if node_type else None),
        url=resolved_url,
        force_session=force,
        conn=conn,
    )
    click.echo(f"Added: {node_id}")


@cli.group()
def session() -> None:
    """Session management."""


@session.command("start")
def session_start() -> None:
    """Generate a new session UUID."""
    click.echo(str(uuid.uuid4()))


@cli.command()
@click.argument("query_text")
@click.option("--top", "top_k", type=int, default=None, help="Number of results (default: 10).")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def query(query_text: str, top_k: int | None, as_json: bool) -> None:
    """Query your memory."""
    result = retrieve(query_text, top_k=top_k)
    if as_json:
        click.echo(format_result_json(result))
        return
    format_result_human(result)


@cli.command()
@click.argument("question", required=False)
@click.option("--model", default=DEFAULT_CHAT_MODEL, show_default=True, help="Copilot model to use for answering.")
@click.option("--top", "top_k", type=int, default=5, show_default=True, help="Number of PAM results to ground each reply on.")
@click.option("--show-context", is_flag=True, help="Print the retrieved PAM context before each answer.")
def chat(question: str | None, model: str, top_k: int, show_context: bool) -> None:
    """Chat with a Copilot model grounded in PAM retrieval."""
    if question is not None:
        response = _answer_chat_query(question, model=model, top_k=top_k)
        if show_context:
            click.echo("PAM context:")
            click.echo(response.retrieved_context)
            click.echo("")
        click.echo(response.answer)
        return

    click.echo("PAM chat. Submit an empty line to exit.\n")
    while True:
        try:
            raw_question = click.prompt("You", prompt_suffix=": ", default="", show_default=False)
        except (EOFError, KeyboardInterrupt, click.Abort):
            click.echo("")
            break

        if not raw_question.strip():
            break

        response = _answer_chat_query(raw_question, model=model, top_k=top_k)
        if show_context:
            click.echo("\nPAM context:")
            click.echo(response.retrieved_context)
        click.echo(f"\nAssistant: {response.answer}\n")

    click.echo("PAM chat ended.")


@cli.command("upvote")
@click.argument("node_id")
@click.pass_context
def upvote_cmd(ctx: click.Context, node_id: str) -> None:
    """Upvote a memory node."""
    _echo_on_success(
        upvote(ctx.obj["conn"], node_id),
        f"Upvoted: {node_id}",
        f"Node not found: {node_id}",
    )


@cli.command("downvote")
@click.argument("node_id")
@click.pass_context
def downvote_cmd(ctx: click.Context, node_id: str) -> None:
    """Downvote a memory node."""
    _echo_on_success(
        downvote(ctx.obj["conn"], node_id),
        f"Downvoted: {node_id}",
        f"Node not found: {node_id}",
    )


@cli.command("pin")
@click.argument("node_id")
@click.pass_context
def pin_cmd(ctx: click.Context, node_id: str) -> None:
    """Pin a node (importance = 1.0, immune to decay)."""
    _echo_on_success(
        pin(ctx.obj["conn"], node_id),
        f"Pinned: {node_id}",
        f"Node not found: {node_id}",
    )


@cli.command("supersede")
@click.argument("old_node_id")
@click.argument("new_node_id")
@click.pass_context
def supersede_cmd(ctx: click.Context, old_node_id: str, new_node_id: str) -> None:
    """Mark new_node as superseding old_node."""
    _echo_on_success(
        supersede(ctx.obj["conn"], new_node_id, old_node_id),
        f"Superseded: {old_node_id} -> {new_node_id}",
        "One or both nodes not found.",
    )


@cli.command()
@click.pass_context
def decay(ctx: click.Context) -> None:
    """Run importance decay on all nodes."""
    result = apply_decay(ctx.obj["conn"])
    click.echo(
        f"Processed: {result['nodes_processed']}, Decayed: {result['nodes_decayed']}, Archived: {result['nodes_archived']}"
    )


@cli.command("unarchive")
@click.argument("node_id")
@click.pass_context
def unarchive_cmd(ctx: click.Context, node_id: str) -> None:
    """Restore an archived node."""
    _echo_on_success(
        unarchive(ctx.obj["conn"], node_id),
        f"Unarchived: {node_id}",
        f"Node not found or not archived: {node_id}",
    )


@cli.command()
@click.argument("node_id")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def show(ctx: click.Context, node_id: str, as_json: bool) -> None:
    """Show details of a specific node."""
    node = get_node(ctx.obj["conn"], node_id)
    if not node:
        _exit_with_error(f"Not found: {node_id}")
    if as_json:
        click.echo(format_node_json(node))
        return
    format_node_human(node)


@cli.command("list")
@click.option("--type", "node_type", type=click.Choice(["event", "entity", "note", "source"], case_sensitive=False))
@click.option("--since", default=None, help="Show nodes with valid_at after this date (ISO8601 or YYYY-MM-DD).")
@click.option("--status", type=click.Choice(["active", "draft", "reference", "archived"], case_sensitive=False), default="active")
@click.option("--limit", type=int, default=20)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def list_cmd(
    ctx: click.Context,
    node_type: str | None,
    since: str | None,
    status: str,
    limit: int,
    as_json: bool,
) -> None:
    """List nodes with filters."""
    since_dt = parse_datetime(since) if since else None
    nodes = list_nodes(
        ctx.obj["conn"],
        type=node_type.lower() if node_type else None,
        status=status.lower(),
        since=since_dt,
        limit=limit,
    )
    if as_json:
        click.echo(format_nodes_json(nodes))
        return
    for node in nodes:
        format_node_summary(node)


@cli.command()
@click.argument("node_id")
@click.pass_context
def graph(ctx: click.Context, node_id: str) -> None:
    """Show all edges for a node."""
    conn = ctx.obj["conn"]
    node = get_node(conn, node_id)
    if not node:
        _exit_with_error(f"Not found: {node_id}")

    click.echo(f"Node: {node.title} ({node.type}, {node.status})")
    click.echo()

    outgoing = get_edges_from(conn, node_id)
    if outgoing:
        click.echo("Outgoing edges:")
        for edge in outgoing:
            click.echo(_format_graph_edge(conn, edge, incoming=False))

    incoming = get_edges_to(conn, node_id)
    if incoming:
        click.echo("Incoming edges:")
        for edge in incoming:
            click.echo(_format_graph_edge(conn, edge, incoming=True))


@cli.command()
@click.option(
    "--backfill-embeddings",
    "backfill_embeddings_flag",
    is_flag=True,
    help="After migrations, embed every node that has no vector yet.",
)
@click.pass_context
def migrate(ctx: click.Context, backfill_embeddings_flag: bool) -> None:
    """Apply pending schema migrations."""
    conn = ctx.obj["conn"]
    initialize(conn)
    click.echo("Migrations applied.")
    if not backfill_embeddings_flag:
        return
    try:
        stats = backfill_embeddings(conn)
    except EmbeddingsUnavailable as exc:
        raise click.ClickException(str(exc))
    click.echo(
        f"Embeddings backfill: {stats.embedded} embedded / "
        f"{stats.skipped_empty_text} skipped (empty text) / "
        f"{stats.failed} failed / {stats.total} candidates."
    )


@cli.command()
@click.option("--json", "as_json", is_flag=True, help="Emit the report as JSON.")
@click.pass_context
def doctor(ctx: click.Context, as_json: bool) -> None:
    """Report database health. Exit 1 if drift detected."""
    conn = ctx.obj["conn"]
    report = doctor_report(conn)
    if as_json:
        click.echo(json.dumps(report, indent=2))
    else:
        click.echo(f"Schema version:           {report['schema_version']}")
        click.echo(f"Integrity check:          {report['integrity_check']}")
        click.echo(f"Nodes:                    {report['nodes_count']}")
        click.echo(f"FTS rows missing:         {report['missing_fts_rows']}")
        click.echo(f"FTS rows orphaned:        {report['orphaned_fts_rows']}")
        click.echo(f"Vector table present:     {report['vec_table_present']}")
        click.echo(f"Embedding model loadable: {report['embeddings_model_available']}")
        click.echo(f"Nodes without embedding:  {report['nodes_missing_embeddings']}")
        click.echo(f"Healthy:                  {report['is_healthy']}")
    if not report["is_healthy"]:
        ctx.exit(1)


@cli.command("rebuild-fts")
@click.pass_context
def rebuild_fts_cmd(ctx: click.Context) -> None:
    """Wipe and rebuild the FTS index from nodes."""
    conn = ctx.obj["conn"]
    indexed = rebuild_fts(conn)
    click.echo(f"FTS rebuilt: {indexed} rows indexed.")


@cli.command()
@click.pass_context
def stats(ctx: click.Context) -> None:
    """Show database statistics."""
    conn = ctx.obj["conn"]
    cursor = conn.cursor()

    click.echo("Nodes:")
    for node_type, count in cursor.execute("SELECT type, COUNT(*) FROM nodes GROUP BY type").fetchall():
        click.echo(f"  {node_type}: {count}")

    click.echo("Statuses:")
    for status, count in cursor.execute("SELECT status, COUNT(*) FROM nodes GROUP BY status").fetchall():
        click.echo(f"  {status}: {count}")

    click.echo("Edges:")
    for relation, count in cursor.execute("SELECT relation, COUNT(*) FROM edges GROUP BY relation").fetchall():
        click.echo(f"  {relation}: {count}")

    fts_count = cursor.execute("SELECT COUNT(*) FROM fts_index").fetchone()[0]
    click.echo(f"FTS index entries: {fts_count}")


def main() -> None:
    cli(obj={})


if __name__ == "__main__":
    main()