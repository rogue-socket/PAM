"""Adapter that exposes tests/fixtures/retrieval_regression_corpus.json as a
harness-compatible fixture for `scripts/run_copilot_cli_eval.py`.

The regression corpus stores items under three top-level keys:
- `articles`: source-typed entries with explicit content + filename
- `notes`: short factual strings
- `thoughts`: short opinion/observation strings
- `queries`: query text + expected_substrings (or expect_empty)

The eval harness expects the shape:
- `corpus`: list of dicts with `key`, `at`, `text`, `ingest_kind`, `session`, optional `filename`/`derived_from`
- `queries`: list of dicts with `query`, `query_type`, `kind`, and either `expected_substrings` or `expect_empty`
- `supersedes`: list of (old_key, new_key)

This adapter does the translation. valid_at is fixed at the corpus's commit
window (2026-04-21) so the regression fixture stays time-stable across
sessions; if the corpus grows real timestamps later, swap to per-item dates.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


CORPUS_PATH = Path(__file__).parent / "fixtures" / "retrieval_regression_corpus.json"
DEFAULT_VALID_AT = "2026-04-21T12:00:00+00:00"
DEFAULT_SESSION = "regression"


def _build_corpus(raw: dict) -> list[dict]:
    items: list[dict] = []

    for idx, article in enumerate(raw.get("articles", [])):
        items.append(
            {
                "key": f"article_{idx}",
                "at": DEFAULT_VALID_AT,
                "session": DEFAULT_SESSION,
                "ingest_kind": "file",
                "text": article["content"],
                "filename": article.get("filename", f"article_{idx}.txt"),
            }
        )

    for idx, note in enumerate(raw.get("notes", [])):
        items.append(
            {
                "key": f"note_{idx}",
                "at": DEFAULT_VALID_AT,
                "session": DEFAULT_SESSION,
                "ingest_kind": "note",
                "text": note if isinstance(note, str) else note.get("content", ""),
            }
        )

    for idx, thought in enumerate(raw.get("thoughts", [])):
        items.append(
            {
                "key": f"thought_{idx}",
                "at": DEFAULT_VALID_AT,
                "session": DEFAULT_SESSION,
                "ingest_kind": "note",
                "text": thought if isinstance(thought, str) else thought.get("content", ""),
            }
        )

    return items


def _build_queries(raw: dict) -> list[dict]:
    queries: list[dict] = []
    for query_case in raw.get("queries", []):
        translated = {
            "query": query_case["query"],
            # Regression corpus does not distinguish query types; tag everything
            # as `lookup` / `direct` so per-type metrics still aggregate cleanly.
            "query_type": "lookup",
            "kind": "direct",
        }
        if query_case.get("expect_empty"):
            translated["expect_empty"] = True
        else:
            translated["expected_substrings"] = list(query_case.get("expected_substrings", []))
        queries.append(translated)
    return queries


@lru_cache(maxsize=1)
def load_regression_eval_fixture() -> dict:
    """Return the regression corpus reshaped for the eval harness."""
    with CORPUS_PATH.open("r", encoding="utf-8") as fh:
        raw = json.load(fh)
    return {
        "corpus": _build_corpus(raw),
        "queries": _build_queries(raw),
        "supersedes": [],
    }


__all__ = ["load_regression_eval_fixture"]
