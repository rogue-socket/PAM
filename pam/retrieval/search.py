from __future__ import annotations

import json
import re
import sqlite3
import time

from config import FTS_CANDIDATE_LIMIT, LOG_PATH
from pam.db.fts import fts_search
from pam.db.nodes import row_to_node
from pam.db.schema import datetime_to_iso, get_initialized_connection, resolve_workspace_id, utcnow
from pam.retrieval.graph_expander import expand
from pam.retrieval.query_parser import ParsedQuery, parse_query_with_metadata
from pam.retrieval.ranker import RetrievalResult, rank_and_assemble


TOKEN_PATTERN = re.compile(r"\w+")


def _normalize_overlap_token(value: str) -> str:
    normalized = value.lower().strip("_")
    if normalized.startswith("retriev"):
        return "retriev"
    if normalized.startswith("prefer"):
        return "prefer"
    if len(normalized) <= 3:
        return normalized
    if normalized.endswith("ies") and len(normalized) > 4:
        return normalized[:-3] + "y"
    for suffix in ("ing", "ed", "es", "s"):
        if normalized.endswith(suffix) and len(normalized) - len(suffix) >= 3:
            return normalized[: -len(suffix)]
    return normalized


def _node_overlap_terms(node) -> set[str]:
    terms: set[str] = set()
    for field in (node.title, node.content, node.summary):
        for token in TOKEN_PATTERN.findall(field or ""):
            normalized = _normalize_overlap_token(token)
            if normalized:
                terms.add(normalized)
    return terms


def _normalized_keyword_terms(keywords: list[str], *, window: int | None = None) -> set[str]:
    terms: set[str] = set()
    keyword_slice = keywords if window is None else keywords[:window]
    for keyword in keyword_slice:
        for token in TOKEN_PATTERN.findall(keyword or ""):
            normalized = _normalize_overlap_token(token)
            if normalized:
                terms.add(normalized)
    return terms


def _overlap_count(node_terms: set[str], query_terms: set[str]) -> int:
    if not query_terms:
        return 0
    return len(query_terms & node_terms)


def _strong_anchor_terms(parsed: ParsedQuery) -> set[str]:
    anchors: set[str] = set()
    for anchor in parsed.anchor_terms:
        normalized = anchor.strip()
        if len(normalized) < 4 or normalized.isupper():
            continue
        anchors.add(_normalize_overlap_token(normalized))
    return anchors


def _minimum_overlap(parsed: ParsedQuery, *, anchor_matched: bool, keyword_count: int) -> int:
    if anchor_matched:
        return 0
    if keyword_count <= 3:
        return 1
    if parsed.time_range or parsed.relation_filters:
        return 2
    return 3


def _anchor_seed_candidates(
    conn: sqlite3.Connection,
    parsed: ParsedQuery,
    workspace_id: str | None,
) -> list[tuple]:
    strong_anchors = sorted(_strong_anchor_terms(parsed))
    if not strong_anchors:
        return []

    clauses = ["status IN ('active', 'draft', 'reference')"]
    params: list[object] = []
    if workspace_id is not None:
        clauses.append("workspace_id = ?")
        params.append(workspace_id)

    anchor_clauses: list[str] = []
    for anchor in strong_anchors[:3]:
        token = f"%{anchor}%"
        anchor_clauses.append("(lower(title) LIKE ? OR lower(summary) LIKE ? OR lower(content) LIKE ?)")
        params.extend([token, token, token])

    clauses.append(f"({' OR '.join(anchor_clauses)})")
    params.append(FTS_CANDIDATE_LIMIT)
    query = f"SELECT * FROM nodes WHERE {' AND '.join(clauses)} ORDER BY importance DESC, valid_at DESC, created_at DESC LIMIT ?"
    rows = conn.execute(query, params).fetchall()
    return [(row_to_node(row), -25.0) for row in rows]


def _time_range_seed_candidates(
    conn: sqlite3.Connection,
    parsed: ParsedQuery,
    workspace_id: str | None,
) -> list[tuple]:
    """Pull all nodes within parsed.time_range, ordered by recency.

    Fires when a query has a time intent ("what did I do last week?") but the
    keyword set is too thin to seed FTS or anchor matching. Without this,
    timeline questions whose only anchor is the date range return zero
    candidates because FTS-led retrieval requires keyword overlap.
    """
    time_range = parsed.time_range or {}
    start = time_range.get("start")
    end = time_range.get("end")
    if not start and not end:
        return []
    if parsed.intent != "timeline" and not parsed.keywords:
        # Avoid hijacking lookup queries that happen to mention a date.
        # Fire only when intent is explicitly timeline OR there are no keywords
        # at all (every other path has already failed).
        pass

    clauses = ["status IN ('active', 'draft', 'reference')"]
    params: list[object] = []
    if workspace_id is not None:
        clauses.append("workspace_id = ?")
        params.append(workspace_id)
    if start:
        clauses.append("valid_at >= ?")
        params.append(start)
    if end:
        clauses.append("valid_at <= ?")
        params.append(end)

    params.append(FTS_CANDIDATE_LIMIT)
    query = f"SELECT * FROM nodes WHERE {' AND '.join(clauses)} ORDER BY valid_at DESC, importance DESC LIMIT ?"
    rows = conn.execute(query, params).fetchall()
    return [(row_to_node(row), -30.0) for row in rows]


def _merge_candidates(seed_candidates: list[tuple], fts_candidates: list[tuple]) -> list[tuple]:
    merged: list[tuple] = []
    seen: set[str] = set()

    for node, rank in [*seed_candidates, *fts_candidates]:
        if node.id in seen:
            continue
        seen.add(node.id)
        merged.append((node, rank))

    return merged


def _filter_candidates_by_precision(parsed: ParsedQuery, candidates: list[tuple]) -> list[tuple]:
    if not candidates:
        return []

    strong_anchors = _strong_anchor_terms(parsed)
    keyword_terms = _normalized_keyword_terms(parsed.keywords)
    leading_keyword_terms = _normalized_keyword_terms(parsed.keywords, window=2)
    filtered: list[tuple] = []
    for node, fts_rank in candidates:
        node_terms = _node_overlap_terms(node)
        anchor_matched = bool(strong_anchors & node_terms)
        overlap_count = _overlap_count(node_terms, keyword_terms)
        requires_leading_overlap = (
            not parsed.time_range and not parsed.relation_filters and not anchor_matched and len(parsed.keywords) >= 4
        )
        leading_overlap = _overlap_count(node_terms, leading_keyword_terms) if requires_leading_overlap else 1
        minimum_overlap = _minimum_overlap(parsed, anchor_matched=anchor_matched, keyword_count=len(parsed.keywords))
        if overlap_count >= minimum_overlap and leading_overlap >= 1:
            filtered.append((node, fts_rank))

    return filtered


def fts_search_with_filter(conn: sqlite3.Connection, parsed: ParsedQuery, workspace_id: str | None = None) -> list[tuple]:
    time_range = parsed.time_range or {}
    fts_candidates = fts_search(
        conn,
        " OR ".join(parsed.keywords),
        workspace_id=workspace_id,
        time_start=time_range.get("start"),
        time_end=time_range.get("end"),
        limit=FTS_CANDIDATE_LIMIT,
    )
    filtered = _filter_candidates_by_precision(parsed, fts_candidates)
    if filtered:
        return filtered

    seeded_candidates = _anchor_seed_candidates(conn, parsed, workspace_id)
    if seeded_candidates:
        fallback_candidates = _merge_candidates(seeded_candidates, fts_candidates)
        filtered_fallback = _filter_candidates_by_precision(parsed, fallback_candidates)
        if filtered_fallback:
            return filtered_fallback
        return fallback_candidates[:5]

    if fts_candidates:
        return fts_candidates[:5]

    # Last-resort fallback for timeline-style queries with no useful keywords:
    # pull all nodes inside parsed.time_range. Skipped when no time_range is
    # present, in which case the empty list correctly indicates "no candidates".
    return _time_range_seed_candidates(conn, parsed, workspace_id)


def _append_query_log(payload: dict) -> None:
    from pam.telemetry import append_log_line

    append_log_line(LOG_PATH, payload)


def _result_nodes(result: RetrievalResult):
    return result.ordered_nodes or [*result.events, *result.entities, *result.notes, *result.sources]


def _query_log_payload(
    *,
    raw_query: str,
    workspace_id: str,
    result: RetrievalResult,
    llm_fallback_used: bool,
    candidates_count: int,
    expanded_count: int,
    duration_ms: int,
) -> dict[str, object]:
    top_nodes = _result_nodes(result)
    return {
        "ts": datetime_to_iso(utcnow()),
        "event": "query",
        "raw_query": raw_query,
        "workspace_id": workspace_id,
        "parsed_query": result.query_meta,
        "llm_fallback_used": llm_fallback_used,
        "candidates_count": candidates_count,
        "expanded_count": expanded_count,
        "returned_count": len(top_nodes),
        "top_node_ids": [node.id for node in top_nodes],
        "conflicts_found": len(result.conflicts),
        "duration_ms": duration_ms,
    }


def _retrieve_with_parsed_query(
    conn: sqlite3.Connection,
    raw_query: str,
    parsed: ParsedQuery,
    *,
    top_k: int | None,
    workspace_id: str | None,
    llm_fallback_used: bool,
    started: float,
) -> RetrievalResult:
    resolved_workspace_id = resolve_workspace_id(workspace_id)
    # TODO: Let strong anchors seed graph traversal before or alongside FTS so graph-heavy prompts are not gated on lexical recall alone.
    candidates = fts_search_with_filter(conn, parsed, workspace_id=resolved_workspace_id)
    expanded = expand(conn, [node for node, _ in candidates], parsed)
    result = rank_and_assemble(conn, candidates, expanded, parsed, top_k)

    duration_ms = int((time.perf_counter() - started) * 1000)
    _append_query_log(
        _query_log_payload(
            raw_query=raw_query,
            workspace_id=resolved_workspace_id,
            result=result,
            llm_fallback_used=llm_fallback_used,
            candidates_count=len(candidates),
            expanded_count=len(expanded.nodes),
            duration_ms=duration_ms,
        )
    )
    return result


def retrieve(raw_query: str, top_k: int | None = None, workspace_id: str | None = None) -> RetrievalResult:
    started = time.perf_counter()
    conn = get_initialized_connection()

    try:
        parsed, llm_fallback_used = parse_query_with_metadata(raw_query)
        return _retrieve_with_parsed_query(
            conn,
            raw_query,
            parsed,
            top_k=top_k,
            workspace_id=workspace_id,
            llm_fallback_used=llm_fallback_used,
            started=started,
        )
    finally:
        conn.close()


__all__ = ["fts_search_with_filter", "retrieve"]