from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal

from config import (
    LLM_CLAUDE_CODE_MODEL,
    LLM_PROVIDER,
    LLM_QUERY_PARSER_MODEL,
    LLM_QUERY_PARSER_OPENAI_MODEL,
    LLM_TIMEOUT_SECONDS,
)
from pam.llm_clients import (
    LLMUnavailableError as _SharedLLMUnavailableError,
    call_claude_code,
    extract_anthropic_text,
    extract_openai_text,
    unwrap_json_response,
)


logger = logging.getLogger(__name__)

KEYWORD_PATTERN = re.compile(r"\w+")
DATE_TOKEN_PATTERN = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
DATE_RANGE_PATTERN = re.compile(r"\b(?:between|from)\s+(\d{4}-\d{2}-\d{2})\s+(?:and|to)\s+(\d{4}-\d{2}-\d{2})\b")
SINCE_PATTERN = re.compile(r"\b(?:since|from)\s+(\d{4}-\d{2}-\d{2})\b")
AFTER_PATTERN = re.compile(r"\bafter\s+(\d{4}-\d{2}-\d{2})\b")
BEFORE_PATTERN = re.compile(r"\bbefore\s+(\d{4}-\d{2}-\d{2})\b")
TIMELINE_HINT_PATTERN = re.compile(r"\b(when|timeline|history|recent|recently|earlier|latest|today|yesterday|week)\b")


# Re-exported alias of the canonical exception in pam.llm_clients so existing
# importers (`from pam.retrieval.query_parser import LLMUnavailableError`) keep
# working AND `except LLMUnavailableError` catches the same class regardless of
# which module raised it.
LLMUnavailableError = _SharedLLMUnavailableError

VALID_INTENTS = {"lookup", "timeline", "summarize", "reason"}
VALID_RELATIONS = {"REFERS_TO", "DERIVED_FROM", "RELATED", "CONTRADICTS", "SUPERSEDES"}
VALID_RELATION_DIRECTIONS = {"incoming", "outgoing", "both"}
VALID_ANSWER_MODES = {"node", "relationship"}
VALID_QUESTION_SHAPES = {"lookup", "relationship", "influence", "evolution", "theme", "gap"}
STOP_WORDS = {
    "the",
    "a",
    "an",
    "is",
    "was",
    "are",
    "were",
    "in",
    "on",
    "at",
    "that",
    "and",
    "to",
    "for",
    "of",
    "with",
    "by",
    "from",
    "what",
    "when",
    "where",
    "how",
    "who",
    "did",
    "do",
    "does",
    "i",
    "my",
    "me",
    "about",
    "which",
    "why",
    "between",
    "someone",
    "asks",
    "like",
    "tell",
    "tells",
    "told",
    "said",
    "says",
    "once",
    "before",
    "after",
    "long",
    "without",
    "current",
    "debate",
    "should",
    "went",
    "rule",
    "kept",
    "quietly",
    "useful",
    "prefer",
    "over",
    "has",
    "memory",
    "warns",
    "during",
    "feature",
    "through",
    "better",
    "note",
    "memo",
    "update",
    "proposed",
    "member",
    "observed",
    "justifies",
    "paying",
    "extra",
    "because",
    "statement",
    "suggests",
    "only",
    "choice",
    "stayed",
    "even",
    "though",
    "cost",
    "more",
    "quote",
    "made",
    "happened",
    "say",
}
SUPERSEDES_PATTERN = re.compile(r"\b(replace|replaced|replaces|replacement|supersede|superseded|supersedes)\b")
DERIVED_FROM_PATTERN = re.compile(
    r"\b(derived from|derive from|comes from|come from|came from|based on|grew out of|grow out of|grown out of)\b"
)
REFERS_TO_PATTERN = re.compile(r"\b(mention|mentions|mentioned|refer to|refers to|referred to)\b")
CONTRADICTS_PATTERN = re.compile(
    r"\b(conflict|conflicts|conflicted|contradict|contradicts|contradicted|contradiction|contradictions|contradictory)\b"
)
RELATED_PATTERN = re.compile(r"\b(related to|relate to|relates to|connected to|connection between|relationship between|relationships)\b")
SUPERSEDES_INCOMING_PATTERN = re.compile(
    r"\breplacement for\b"
    r"|\b(?:what|which|who)\b.*\b(?:replaced|superseded)\b(?!\s+by\b)"
)
SUPERSEDES_OUTGOING_PATTERN = re.compile(
    r"\bwhat\s+(?:did|does)\b.*\b(?:replace|supersede)\b"
    r"|\b(?:replaced by|superseded by)\b"
)
DERIVED_FROM_OUTGOING_PATTERN = re.compile(
    r"\b(?:what|which)\s+(?:source|document|file|url|link|article|checklist|memo|transcript|handbook|report|bulletin|faq)\b"
    r".*\b(?:derived from|derive from|comes from|come from|came from|based on|grew out of|grow out of|grown out of)\b"
    r"|\bwhat\s+(?:is|was|does)\b.*\b(?:derived from|comes from|come from|came from|based on|grew out of|grow out of|grown out of)\b"
)
DERIVED_FROM_INCOMING_PATTERN = re.compile(
    r"\b(?:what|which)\s+(?:note|notes|memory|memories|idea|event|task|thought)\b"
    r".*\b(?:derived from|derive from|comes from|come from|came from|based on|grew out of|grow out of|grown out of)\b"
)
REFERS_TO_INCOMING_PATTERN = re.compile(r"\b(?:what|which|who)\s+(?:mentions|mentioned|refers to|referred to)\b")
REFERS_TO_OUTGOING_PATTERN = re.compile(r"\bwhat\s+(?:did|does)\b.*\bmention\b")
GENERIC_RELATIONSHIP_PATTERNS = [
    re.compile(r"\bshows up in both\b"),
    re.compile(r"\b(?:what|which)\s+(?:(?:\w+)\s+){0,2}(?:memo|memory|prompt|statement|evidence|document|source)\s+(?:says|suggests|justifies)\b"),
    re.compile(r"\bties\b.*\bto\b"),
    re.compile(r"\bcompared with\b"),
    re.compile(r"\binstead of overwriting\b"),
    re.compile(r"\blost out after\b"),
]
INFLUENCE_QUERY_PATTERN = re.compile(
    r"\b(influence|influenced|influences|shaped|shapes|shaping|inform|informed|informs|informing|drove|drive|"
    r"driven by|led to|source of|came from|comes from|derive from|derived from|based on|grew out of)\b"
)
EVOLUTION_QUERY_PATTERN = re.compile(
    r"\b(evolve|evolved|evolves|evolving|evolution|changed over time|change over time|replaced|replacement|"
    r"supersede|superseded|supersedes)\b"
)
THEME_QUERY_PATTERN = re.compile(
    r"\b(theme|themes|central|core|common thread|main thread|recurring|recurs|pattern|patterns|keep coming up|"
    r"keeps coming up|connected ideas)\b"
)
GAP_QUERY_PATTERN = re.compile(
    r"\b(gap|gaps|underexplored|under explored|unexplored|not explored|haven't explored|have not explored|"
    r"blind spot|blind spots|adjacent topic|adjacent topics|nearby topic|nearby topics|what next|next topic|"
    r"missing link|missing links)\b"
)


@dataclass
class ParsedQuery:
    keywords: list[str]
    entities: list[str]
    time_range: dict[str, str | None] | None
    intent: Literal["lookup", "timeline", "summarize", "reason"]
    relation_filters: list[str] = field(default_factory=list)
    relation_direction: Literal["incoming", "outgoing", "both"] | None = None
    answer_mode: Literal["node", "relationship"] = "node"
    question_shape: Literal["lookup", "relationship", "influence", "evolution", "theme", "gap"] = "lookup"
    anchor_terms: list[str] = field(default_factory=list)
    time_range_relative: bool = False


def _extract_keywords(query: str) -> list[str]:
    words = [word.lower() for word in KEYWORD_PATTERN.findall(query)]
    return [word for word in words if word and word not in STOP_WORDS and len(word) > 2 and not word.isdigit()][:5]


def _extract_anchor_terms(query: str) -> list[str]:
    anchor_terms: list[str] = []
    seen: set[str] = set()

    for index, token in enumerate(KEYWORD_PATTERN.findall(query)):
        if len(token) <= 2:
            continue
        if index == 0 and token.lower() in STOP_WORDS:
            continue
        if not (token[:1].isupper() or token.isupper()):
            continue

        normalized = token.strip()
        lowered = normalized.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        anchor_terms.append(normalized)

    return anchor_terms[:5]


def _datetime_to_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _day_boundary_iso(target_day: date, boundary: time) -> str:
    return _datetime_to_iso(datetime.combine(target_day, boundary, tzinfo=timezone.utc))


def _time_range(start_day: date | None, end_day: date | None) -> dict[str, str | None]:
    return {
        "start": _day_boundary_iso(start_day, time.min) if start_day is not None else None,
        "end": _day_boundary_iso(end_day, time.max if start_day is not None or end_day is not None else time.max)
        if end_day is not None
        else None,
    }


def _day_range(target_day: date) -> dict[str, str | None]:
    return _time_range(target_day, target_day)


def _week_range(anchor_day: date) -> dict[str, str | None]:
    week_start = anchor_day - timedelta(days=anchor_day.weekday())
    week_end = week_start + timedelta(days=6)
    return _time_range(week_start, week_end)


def _parse_date_token(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _extract_time_range(query: str, today: date) -> dict[str, str | None] | None:
    """Return absolute time window or None.

    For the relative-vs-absolute distinction used by the empty-window
    fallback in search, callers should use `_extract_time_range_with_meta`.
    """
    result, _ = _extract_time_range_with_meta(query, today)
    return result


def _extract_time_range_with_meta(
    query: str, today: date
) -> tuple[dict[str, str | None] | None, bool]:
    """Like `_extract_time_range` but also returns whether the phrase was
    relative-to-now (e.g. "last week", "yesterday", "today", "this week").

    Relative windows that miss every node should fall back to most-recent
    items at search time — explicit-date windows should not.
    """
    lowered = query.lower()

    range_match = DATE_RANGE_PATTERN.search(lowered)
    if range_match:
        start_day = _parse_date_token(range_match.group(1))
        end_day = _parse_date_token(range_match.group(2))
        if start_day is not None and end_day is not None:
            if end_day < start_day:
                start_day, end_day = end_day, start_day
            return _time_range(start_day, end_day), False

    since_match = SINCE_PATTERN.search(lowered)
    if since_match:
        start_day = _parse_date_token(since_match.group(1))
        if start_day is not None:
            return _time_range(start_day, None), False

    after_match = AFTER_PATTERN.search(lowered)
    if after_match:
        start_day = _parse_date_token(after_match.group(1))
        if start_day is not None:
            return _time_range(start_day + timedelta(days=1), None), False

    before_match = BEFORE_PATTERN.search(lowered)
    if before_match:
        end_day = _parse_date_token(before_match.group(1))
        if end_day is not None:
            return {"start": None, "end": _day_boundary_iso(end_day, time.min)}, False

    explicit_dates = DATE_TOKEN_PATTERN.findall(lowered)
    if explicit_dates:
        explicit_day = _parse_date_token(explicit_dates[0])
        if explicit_day is not None:
            return _day_range(explicit_day), False

    if "yesterday" in lowered:
        return _day_range(today - timedelta(days=1)), True
    if "today" in lowered:
        return _day_range(today), True
    if "last week" in lowered:
        return _week_range(today - timedelta(days=7)), True
    if "this week" in lowered:
        return _week_range(today), True

    return None, False


def _infer_question_shape(
    query: str,
    relation_filters: list[str],
) -> Literal["lookup", "relationship", "influence", "evolution", "theme", "gap"]:
    lowered = query.lower()

    if GAP_QUERY_PATTERN.search(lowered):
        return "gap"
    if THEME_QUERY_PATTERN.search(lowered):
        return "theme"
    if EVOLUTION_QUERY_PATTERN.search(lowered):
        return "evolution"
    if INFLUENCE_QUERY_PATTERN.search(lowered):
        return "influence"
    if relation_filters or _has_generic_relationship_intent(query):
        return "relationship"
    return "lookup"


def _default_intent_for_shape(
    question_shape: Literal["lookup", "relationship", "influence", "evolution", "theme", "gap"],
    time_range: dict[str, str | None] | None,
) -> Literal["lookup", "timeline", "summarize", "reason"]:
    if time_range is not None:
        return "timeline"
    if question_shape in {"influence", "theme", "gap", "evolution"}:
        return "reason"
    return "lookup"


def _infer_fallback_intent(
    query: str,
    time_range: dict[str, str | None] | None,
    question_shape: Literal["lookup", "relationship", "influence", "evolution", "theme", "gap"],
) -> Literal["lookup", "timeline", "summarize", "reason"]:
    if TIMELINE_HINT_PATTERN.search(query.lower()):
        return "timeline"
    return _default_intent_for_shape(question_shape, time_range)


def _infer_relation_filters(query: str) -> list[str]:
    lowered = query.lower()
    inferred: list[str] = []

    for pattern, relation in [
        (SUPERSEDES_PATTERN, "SUPERSEDES"),
        (DERIVED_FROM_PATTERN, "DERIVED_FROM"),
        (REFERS_TO_PATTERN, "REFERS_TO"),
        (CONTRADICTS_PATTERN, "CONTRADICTS"),
        (RELATED_PATTERN, "RELATED"),
    ]:
        if pattern.search(lowered):
            inferred.append(relation)

    seen: set[str] = set()
    ordered: list[str] = []
    for relation in inferred:
        if relation in seen:
            continue
        seen.add(relation)
        ordered.append(relation)

    if not ordered:
        question_shape = _infer_question_shape(query, ordered)
        for relation in {
            "evolution": ["SUPERSEDES"],
            "influence": ["DERIVED_FROM", "REFERS_TO", "RELATED"],
            "theme": ["RELATED"],
            "gap": ["RELATED"],
        }.get(question_shape, []):
            if relation in seen:
                continue
            seen.add(relation)
            ordered.append(relation)

    return ordered


def _has_generic_relationship_intent(query: str) -> bool:
    lowered = query.lower()
    return any(pattern.search(lowered) for pattern in GENERIC_RELATIONSHIP_PATTERNS)


def _infer_relation_direction(
    query: str,
    relation_filters: list[str],
) -> Literal["incoming", "outgoing", "both"] | None:
    if not relation_filters:
        return None

    lowered = query.lower()
    relations = set(relation_filters)

    if "SUPERSEDES" in relations:
        if SUPERSEDES_INCOMING_PATTERN.search(lowered):
            return "incoming"
        if SUPERSEDES_OUTGOING_PATTERN.search(lowered):
            return "outgoing"

    if "DERIVED_FROM" in relations:
        if DERIVED_FROM_OUTGOING_PATTERN.search(lowered):
            return "outgoing"
        if DERIVED_FROM_INCOMING_PATTERN.search(lowered):
            return "incoming"

    if "REFERS_TO" in relations:
        if REFERS_TO_INCOMING_PATTERN.search(lowered):
            return "incoming"
        if REFERS_TO_OUTGOING_PATTERN.search(lowered):
            return "outgoing"

    return "both"


def _infer_answer_mode(
    query: str,
    relation_filters: list[str],
    question_shape: Literal["lookup", "relationship", "influence", "evolution", "theme", "gap"],
) -> Literal["node", "relationship"]:
    if question_shape != "lookup":
        return "relationship"
    if relation_filters:
        return "relationship"
    if _has_generic_relationship_intent(query):
        return "relationship"
    return "node"


def fallback_parse(query: str, today: date | None = None) -> ParsedQuery:
    current_date = today or date.today()
    time_range, time_range_relative = _extract_time_range_with_meta(query, current_date)
    relation_filters = _infer_relation_filters(query)
    question_shape = _infer_question_shape(query, relation_filters)
    return ParsedQuery(
        keywords=_extract_keywords(query),
        entities=[],
        time_range=time_range,
        intent=_infer_fallback_intent(query, time_range, question_shape),
        relation_filters=relation_filters,
        relation_direction=_infer_relation_direction(query, relation_filters),
        answer_mode=_infer_answer_mode(query, relation_filters, question_shape),
        question_shape=question_shape,
        anchor_terms=_extract_anchor_terms(query),
        time_range_relative=time_range_relative,
    )


def _validate_iso8601(value: str | None) -> str | None:
    if value is None:
        return None
    datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value


def _build_prompt(raw_query: str, today: date) -> str:
    return (
        "Convert the following query into a structured search specification.\n"
        "Return ONLY valid JSON matching this schema exactly:\n"
        "{\n"
        '  "keywords": string[],\n'
        '  "entities": string[],\n'
        '  "time_range": {\n'
        '    "start": "ISO8601" | null,\n'
        '    "end": "ISO8601" | null\n'
        "  },\n"
        '  "intent": "lookup" | "timeline" | "summarize" | "reason",\n'
        '  "relation_filters": ("REFERS_TO" | "DERIVED_FROM" | "RELATED" | "CONTRADICTS" | "SUPERSEDES")[],\n'
        '  "relation_direction": "incoming" | "outgoing" | "both" | null,\n'
        '  "answer_mode": "node" | "relationship",\n'
        '  "question_shape": "lookup" | "relationship" | "influence" | "evolution" | "theme" | "gap",\n'
        '  "anchor_terms": string[]\n'
        "}\n\n"
        f"Today's date: {today.isoformat()}\n"
        f"Query: {raw_query}"
    )


def _configured_provider() -> str:
    return (LLM_PROVIDER or "").strip().lower()


def _invoke_llm(raw_query: str, today: date) -> str:
    prompt = _build_prompt(raw_query, today)
    provider = _configured_provider()

    if provider == "anthropic":
        try:
            from anthropic import Anthropic
        except ImportError as exc:
            raise LLMUnavailableError("anthropic SDK is not installed") from exc

        client = Anthropic(timeout=LLM_TIMEOUT_SECONDS)
        response = client.messages.create(
            model=LLM_QUERY_PARSER_MODEL,
            max_tokens=300,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        return extract_anthropic_text(response)

    if provider == "openai":
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise LLMUnavailableError("openai SDK is not installed") from exc

        client = OpenAI(timeout=LLM_TIMEOUT_SECONDS)
        response = client.responses.create(
            model=LLM_QUERY_PARSER_OPENAI_MODEL,
            input=prompt,
            temperature=0,
        )
        return extract_openai_text(response)

    if provider == "claude_code":
        return call_claude_code(
            prompt,
            model=LLM_CLAUDE_CODE_MODEL,
            timeout=LLM_TIMEOUT_SECONDS,
        )

    raise RuntimeError(f"Unsupported LLM provider: {LLM_PROVIDER}")


def _coerce_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _coerce_time_range(value: object) -> dict[str, str | None] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("time_range must be an object or null")

    start = value.get("start")
    end = value.get("end")
    if start is not None and not isinstance(start, str):
        raise ValueError("time_range.start must be a string or null")
    if end is not None and not isinstance(end, str):
        raise ValueError("time_range.end must be a string or null")

    return {"start": _validate_iso8601(start), "end": _validate_iso8601(end)}


def _coerce_relation_filters(value: object) -> list[str]:
    if not isinstance(value, list):
        return []

    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        relation = item.strip().upper()
        if relation not in VALID_RELATIONS or relation in seen:
            continue
        seen.add(relation)
        normalized.append(relation)
    return normalized


def _coerce_relation_direction(value: object) -> Literal["incoming", "outgoing", "both"] | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None

    normalized = value.strip().lower()
    if normalized not in VALID_RELATION_DIRECTIONS:
        return None
    return normalized


def _coerce_answer_mode(
    value: object,
    raw_query: str,
    relation_filters: list[str],
    question_shape: Literal["lookup", "relationship", "influence", "evolution", "theme", "gap"],
) -> Literal["node", "relationship"]:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in VALID_ANSWER_MODES:
            return normalized
    return _infer_answer_mode(raw_query, relation_filters, question_shape)


def _coerce_question_shape(
    value: object,
    raw_query: str,
    relation_filters: list[str],
) -> Literal["lookup", "relationship", "influence", "evolution", "theme", "gap"]:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in VALID_QUESTION_SHAPES:
            return normalized
    return _infer_question_shape(raw_query, relation_filters)


def _coerce_anchor_terms(value: object, raw_query: str) -> list[str]:
    fallback_anchors = _extract_anchor_terms(raw_query)
    if not isinstance(value, list):
        return fallback_anchors

    anchors = list(fallback_anchors)
    seen = {anchor.lower() for anchor in anchors}
    for item in value:
        if not isinstance(item, str):
            continue
        anchor = item.strip()
        if len(anchor) <= 2:
            continue
        lowered = anchor.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        anchors.append(anchor)
    return anchors[:5]


def _normalize_parsed_query(payload: dict[str, object], raw_query: str) -> ParsedQuery:
    keywords = _coerce_string_list(payload.get("keywords"))
    if not keywords:
        keywords = _extract_keywords(raw_query)

    entities = _coerce_string_list(payload.get("entities"))
    time_range = _coerce_time_range(payload.get("time_range"))
    relation_filters = _coerce_relation_filters(payload.get("relation_filters"))
    if not relation_filters:
        relation_filters = _infer_relation_filters(raw_query)

    question_shape = _coerce_question_shape(payload.get("question_shape"), raw_query, relation_filters)
    relation_direction = _coerce_relation_direction(payload.get("relation_direction"))
    if relation_direction is None:
        relation_direction = _infer_relation_direction(raw_query, relation_filters)

    answer_mode = _coerce_answer_mode(payload.get("answer_mode"), raw_query, relation_filters, question_shape)

    intent = payload.get("intent")
    if not isinstance(intent, str) or intent not in VALID_INTENTS:
        intent = _default_intent_for_shape(question_shape, time_range)

    lowered = raw_query.lower()
    time_range_relative = time_range is not None and any(
        phrase in lowered for phrase in ("yesterday", "today", "last week", "this week")
    )

    return ParsedQuery(
        keywords=keywords,
        entities=entities,
        time_range=time_range,
        intent=intent,
        relation_filters=relation_filters,
        relation_direction=relation_direction,
        answer_mode=answer_mode,
        question_shape=question_shape,
        anchor_terms=_coerce_anchor_terms(payload.get("anchor_terms"), raw_query),
        time_range_relative=time_range_relative,
    )


def parse_query(raw_query: str, today: date | None = None) -> ParsedQuery:
    parsed, _ = parse_query_with_metadata(raw_query, today=today)
    return parsed


def parse_query_with_metadata(raw_query: str, today: date | None = None) -> tuple[ParsedQuery, bool]:
    # TODO: Recognize graph-native question classes and preserve concept or alias anchors here instead of collapsing many prompts into generic lookup or relationship metadata.
    current_date = today or date.today()
    try:
        response = _invoke_llm(raw_query, current_date)
        payload = json.loads(unwrap_json_response(response))
        if not isinstance(payload, dict):
            raise ValueError("LLM response must be a JSON object")
        return _normalize_parsed_query(payload, raw_query), False
    except LLMUnavailableError:
        return fallback_parse(raw_query, current_date), True
    except Exception as exc:
        logger.warning("Falling back to deterministic query parsing: %s", exc)
        return fallback_parse(raw_query, current_date), True


__all__ = [
    "ParsedQuery",
    "VALID_ANSWER_MODES",
    "VALID_QUESTION_SHAPES",
    "STOP_WORDS",
    "VALID_INTENTS",
    "VALID_RELATION_DIRECTIONS",
    "VALID_RELATIONS",
    "fallback_parse",
    "parse_query",
    "parse_query_with_metadata",
]