from __future__ import annotations

import json
import logging
import os

from config import (
    ENTITY_CATEGORIES,
    LLM_CLAUDE_CODE_MODEL,
    LLM_INGESTION_MODEL,
    LLM_PROVIDER,
    LLM_TIMEOUT_SECONDS,
    MAX_ENTITIES_PER_INGESTION,
)
from pam.llm_clients import (
    LLMUnavailableError,
    call_claude_code,
    extract_anthropic_text,
    extract_openai_text,
    unwrap_json_response,
)


logger = logging.getLogger(__name__)

SUMMARY_PROMPT = """You are a memory assistant. Summarize the following in 1–2 sentences, capturing the key idea.
Return ONLY the summary string. No preamble, no quotes.

Content: {content}
"""

ENTITY_PROMPT = """Extract named entities from the following text.
Rules:
- Return a JSON array of objects: [{{"name": str, "category": str}}]
- category must be one of: person, tool, concept, project, place, organization
- Maximum 5 entities total
- Only include entities central to the text, not incidental mentions
- Return [] if no strong entities found
- Return ONLY valid JSON. No explanation.

Text: {content}
"""

EDGE_FACT_PROMPT = """Given this text and the entity \"{entity_name}\", write ONE short sentence describing how
the text relates to the entity.
Return ONLY the sentence. No preamble.

Text: {content}
"""


def _safe_llm_text(prompt: str, warning_message: str, *warning_args: object) -> str | None:
    try:
        return _call_llm(prompt).strip()
    except LLMUnavailableError:
        return None
    except Exception as exc:
        logger.warning(warning_message, *warning_args, exc)
        return None


def _call_llm(prompt: str) -> str:
    """Call the configured LLM provider and return raw text."""
    provider = (LLM_PROVIDER or "").strip().lower()
    if provider == "anthropic":
        try:
            from anthropic import Anthropic
        except ImportError as exc:
            raise LLMUnavailableError("anthropic SDK is not installed") from exc

        client = Anthropic(timeout=LLM_TIMEOUT_SECONDS)
        response = client.messages.create(
            model=LLM_INGESTION_MODEL,
            max_tokens=400,
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
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
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

    raise ValueError(f"Unsupported LLM provider: {LLM_PROVIDER}")


def summarize(content: str) -> str:
    """Return a 1-2 sentence summary. On failure, return an empty string."""
    response = _safe_llm_text(
        SUMMARY_PROMPT.format(content=content),
        "LLM summarize failed: %s",
    )
    return response or ""


def extract_entities(content: str) -> list[dict]:
    """Return parsed entities. On failure, return an empty list."""
    raw_response = _safe_llm_text(
        ENTITY_PROMPT.format(content=content),
        "LLM entity extraction failed: %s",
    )
    if raw_response is None:
        return []

    try:
        payload = json.loads(unwrap_json_response(raw_response))
    except json.JSONDecodeError as exc:
        logger.warning("LLM entity extraction returned invalid JSON: %s", exc)
        return []

    if not isinstance(payload, list):
        logger.warning("LLM entity extraction returned non-list payload")
        return []

    entities: list[dict] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        category = str(item.get("category", "")).strip().lower()
        if not name or category not in ENTITY_CATEGORIES:
            continue
        entities.append({"name": name, "category": category})
        if len(entities) >= MAX_ENTITIES_PER_INGESTION:
            break
    return entities


def generate_edge_fact(content: str, entity_name: str) -> str:
    """Return one sentence describing how content relates to the entity. On failure, return an empty string."""
    response = _safe_llm_text(
        EDGE_FACT_PROMPT.format(content=content, entity_name=entity_name),
        "LLM edge fact generation failed for %s: %s",
        entity_name,
    )
    return response or ""


__all__ = ["LLMUnavailableError", "extract_entities", "generate_edge_fact", "summarize"]