from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from typing import Literal
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from config import IMPORTANCE_DEFAULT
from pam.db.nodes import find_by_content_hash
from pam.db.schema import get_connection, initialize


TITLE_MAX_LENGTH = 60
VALID_NODE_TYPES = {"event", "note", "source"}
WHITESPACE_PATTERN = re.compile(r"\s+")
TITLE_PATTERN = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


@dataclass
class FetchedSource:
    title: str
    content: str
    content_type: Literal["article", "documentation", "paper", "video", "other"]


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._ignored_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() in {"script", "style"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style"} and self._ignored_depth > 0:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._ignored_depth == 0:
            self._parts.append(data)

    def text(self) -> str:
        return normalize_whitespace(unescape(" ".join(self._parts)))


def normalize_whitespace(text: str) -> str:
    return WHITESPACE_PATTERN.sub(" ", text).strip()


def compute_content_hash(raw_text: str) -> str:
    normalized = normalize_whitespace(raw_text).lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def infer_node_type(input_type: str, explicit_node_type: str | None = None) -> str:
    if explicit_node_type is not None:
        normalized = explicit_node_type.strip().lower()
        if normalized not in VALID_NODE_TYPES:
            raise ValueError(f"Unsupported node_type: {normalized}")
        return normalized

    mapping = {
        "link": "source",
        "task": "event",
        "note": "note",
        "document": "source",
    }
    return mapping.get(input_type, "note")


def _default_metadata(node_type: str, url: str | None = None) -> dict:
    if node_type == "event":
        return {"duration_minutes": None, "source": "manual"}
    if node_type == "note":
        return {"is_belief": False, "confidence": 1.0}
    if node_type == "source":
        return {
            "url": url or "",
            "content_type": _detect_source_content_type(url),
        }
    raise ValueError(f"Unsupported node_type: {node_type}")


def _extract_text_title(raw_text: str) -> str:
    if "\n" in raw_text:
        first_line = raw_text.splitlines()[0].strip()
        if first_line:
            return first_line
    return raw_text[:TITLE_MAX_LENGTH].strip()


def _extract_hostname(url: str) -> str:
    parsed = urlparse(url)
    return parsed.netloc or url


def _detect_source_content_type(url: str | None, header_content_type: str | None = None) -> Literal["article", "documentation", "paper", "video", "other"]:
    lowered_header = (header_content_type or "").lower()
    lowered_url = (url or "").lower()

    if "pdf" in lowered_header or lowered_url.endswith(".pdf"):
        return "paper"
    if any(token in lowered_header for token in ["video", "mpeg", "mp4"]):
        return "video"
    if any(token in lowered_url for token in ["youtube.com", "youtu.be", "vimeo.com"]):
        return "video"
    if any(token in lowered_header for token in ["text/markdown", "text/plain"]):
        return "documentation"
    if any(token in lowered_url for token in ["/docs", "readthedocs", "documentation", "/reference", "/api"]):
        return "documentation"
    if lowered_url:
        return "article"
    return "other"


def _extract_html_title(html_text: str) -> str:
    match = TITLE_PATTERN.search(html_text)
    if not match:
        return ""
    return normalize_whitespace(unescape(match.group(1)))


def _extract_html_text(html_text: str) -> str:
    parser = _HTMLTextExtractor()
    parser.feed(html_text)
    parser.close()
    return parser.text()


def _close_if_possible(value: object) -> None:
    close = getattr(value, "close", None)
    if callable(close):
        close()


def _fallback_source(url: str) -> FetchedSource:
    return FetchedSource(
        title=_extract_hostname(url),
        content=url,
        content_type=_detect_source_content_type(url),
    )


def _fetch_url_content(url: str) -> FetchedSource | None:
    request = Request(url, headers={"User-Agent": "PAM/1.0"})
    try:
        with urlopen(request, timeout=10) as response:
            body_bytes = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
            body_text = body_bytes.decode(charset, errors="replace")
            header_content_type = response.headers.get("Content-Type", "")
    except Exception as exc:
        _close_if_possible(exc)
        return None

    source_type = _detect_source_content_type(url, header_content_type)
    if "html" in header_content_type.lower():
        title = _extract_html_title(body_text) or _extract_hostname(url)
        content = _extract_html_text(body_text) or url
    else:
        title = _extract_hostname(url)
        content = normalize_whitespace(body_text) or url

    return FetchedSource(title=title, content=content, content_type=source_type)


def _resolve_source_content(url: str) -> FetchedSource:
    fetched = _fetch_url_content(url)
    if fetched is not None:
        return fetched
    return _fallback_source(url)


def extract(
    normalized: dict,
    node_type: str | None = None,
    url: str | None = None,
    parent_note_id: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict | str:
    """
    Deterministically derive node fields and perform dedup before any LLM call.

    Returns extracted fields, or an existing node ID when content_hash already exists.
    """
    resolved_node_type = infer_node_type(normalized["input_type"], node_type)

    owns_connection = conn is None
    if conn is None:
        conn = get_connection()
        initialize(conn)

    try:
        content = normalized["raw_text"]
        title = _extract_text_title(content)
        metadata = _default_metadata(resolved_node_type, url=url)

        if resolved_node_type == "source" and url:
            source = _resolve_source_content(url)
            title = source.title
            content = source.content
            metadata = {"url": url, "content_type": source.content_type}
        elif normalized["input_type"] == "link" and url:
            title = _extract_hostname(url)

        content_hash = compute_content_hash(content)
        existing = find_by_content_hash(conn, content_hash, workspace_id=normalized.get("workspace_id"))
        if existing is not None:
            return existing.id

        return {
            "node_type": resolved_node_type,
            "title": title,
            "content": content,
            "summary": "",
            "content_hash": content_hash,
            "created_at": normalized["recorded_at"],
            "valid_at": normalized["provided_at"],
            "updated_at": normalized["recorded_at"],
            "tags": [],
            "session_id": normalized["session_id"],
            "importance": IMPORTANCE_DEFAULT,
            "access_count": 0,
            "status": "active",
            "metadata": metadata,
            "input_type": normalized["input_type"],
            "parent_note_id": parent_note_id,
            "workspace_id": normalized["workspace_id"],
        }
    finally:
        if owns_connection:
            conn.close()


__all__ = [
    "FetchedSource",
    "TITLE_MAX_LENGTH",
    "compute_content_hash",
    "extract",
    "infer_node_type",
    "normalize_whitespace",
]