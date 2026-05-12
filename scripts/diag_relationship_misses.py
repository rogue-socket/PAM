"""Inspect node_scores + score_components for the 3 detailed-relationship misses.

Builds the detailed eval corpus into a temp DB, then prints top-20 ordered nodes
with their post-weight score breakdown for idx 81 / 86 / 87. Resolves Position A
vs Position B parameter questions.
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pam.db.schema as schema_module  # noqa: E402
from pam.agent_interface import ingest_for_agent  # noqa: E402
from pam.db.schema import get_connection, initialize  # noqa: E402
from pam.feedback import supersede  # noqa: E402
from pam.retrieval.query_parser import LLMUnavailableError  # noqa: E402
from pam.retrieval.search import retrieve  # noqa: E402


FIXTURE_PATH = ROOT / ".tmp_manual_cli" / "detailed_memory_eval" / "run_detailed_eval.py"
TMP_DIR = ROOT / ".tmp_manual_cli" / "diag_relationship_misses"
DB_PATH = TMP_DIR / "diag.db"
LOG_PATH = TMP_DIR / "diag.jsonl"
LINK_DIR = TMP_DIR / "link_sources"


TARGETS = [
    {
        "idx": 81,
        "query": "Which memory grew out of the apprentice-bookmark idea?",
        "gold_keys": ["research_file_workshop"],
        "seed_keys": ["research_note_apprentices"],
    },
    {
        "idx": 86,
        "query": "What evidence says provenance should outrank freshness when scores tie?",
        "gold_keys": [],
        "seed_keys": [],
    },
    {
        "idx": 87,
        "query": "What memory says stop words are dropped and ISO dates should stay explicit?",
        "gold_keys": [],
        "seed_keys": [],
    },
]


def load_fixture() -> dict:
    spec = importlib.util.spec_from_file_location("pam_detailed_eval_fixture", FIXTURE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {"corpus": module.CORPUS, "queries": module.QUERIES, "supersedes": module.SUPERSEDES}


def reset_tmp_dir() -> None:
    if TMP_DIR.exists():
        shutil.rmtree(TMP_DIR)
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    LINK_DIR.mkdir(parents=True, exist_ok=True)


def ingest_corpus(fixture: dict) -> dict[str, str]:
    node_ids: dict[str, str] = {}
    for item in fixture["corpus"]:
        valid_at = datetime.fromisoformat(item["at"]).replace(tzinfo=timezone.utc)
        parent = node_ids[item["derived_from"]] if item.get("derived_from") else None
        kind = item["ingest_kind"]
        if kind == "url":
            source_path = LINK_DIR / item["filename"]
            source_path.write_text(item["text"], encoding="utf-8")
            result = ingest_for_agent(
                source_path.resolve().as_uri(),
                session_id=item["session"],
                valid_at=valid_at,
                workspace_id=Path.cwd(),
                parent_note_id=parent,
            )
        elif kind == "file":
            result = ingest_for_agent(
                item["text"],
                kind="source",
                session_id=item["session"],
                valid_at=valid_at,
                workspace_id=Path.cwd(),
                parent_note_id=parent,
            )
        elif kind == "event":
            result = ingest_for_agent(
                item["text"],
                kind="event",
                session_id=item["session"],
                valid_at=valid_at,
                workspace_id=Path.cwd(),
            )
        else:
            result = ingest_for_agent(
                item["text"],
                kind="note",
                session_id=item["session"],
                valid_at=valid_at,
                workspace_id=Path.cwd(),
            )
        node_ids[item["key"]] = result.node_id

    conn = get_connection(DB_PATH)
    try:
        for old_key, new_key in fixture["supersedes"]:
            supersede(conn, node_ids[new_key], node_ids[old_key])
    finally:
        conn.close()
    return node_ids


def find_gold_for_query(query: str, fixture: dict, node_ids: dict[str, str]) -> list[str]:
    """Match expected_substrings against corpus text to identify gold node IDs."""
    target = next(q for q in fixture["queries"] if q["query"] == query)
    expected = [s.lower() for s in target.get("expected_substrings", [])]
    if not expected:
        return []
    matches: list[str] = []
    for item in fixture["corpus"]:
        text_blob = item.get("text", "").lower() + " " + item.get("filename", "").lower() + " " + item.get("title", "").lower()
        if any(s in text_blob for s in expected):
            matches.append(node_ids[item["key"]])
    return matches


def diagnose(target: dict, fixture: dict, node_ids: dict[str, str]) -> None:
    query = target["query"]
    gold_ids = find_gold_for_query(query, fixture, node_ids)
    seed_ids = [node_ids[k] for k in target["seed_keys"] if k in node_ids]

    print(f"\n{'=' * 90}")
    print(f"idx {target['idx']}: {query}")
    print(f"gold node ids: {gold_ids}")
    print(f"seed node ids: {seed_ids}")
    print("=" * 90)

    result = retrieve(query, top_k=20, workspace_id=str(Path.cwd()))

    ordered = result.ordered_nodes
    comps = result.score_components
    print(f"\nanswer_mode={result.query_meta.get('answer_mode')}  "
          f"question_shape={result.query_meta.get('question_shape')}  "
          f"relation_filters={result.query_meta.get('relation_filters')}")
    print(f"\nTop-{len(ordered)} ordered_nodes (* = gold, S = seed):")
    print(f"{'rk':<3} {'mark':<3} {'type':<8} {'total':>7} {'text':>7} {'vec':>7} {'rec':>7} {'imp':>7} {'ent':>5} {'title':<50}")
    for rk, node in enumerate(ordered, start=1):
        mark = ""
        if node.id in gold_ids:
            mark += "*"
        if node.id in seed_ids:
            mark += "S"
        c = comps.get(node.id, {})
        total = sum(c.values()) if c else 0.0
        print(
            f"{rk:<3} {mark:<3} {node.type:<8} {total:>7.3f} "
            f"{c.get('text_relevance', 0):>7.3f} "
            f"{c.get('vector_similarity', 0):>7.3f} "
            f"{c.get('recency', 0):>7.3f} "
            f"{c.get('importance', 0):>7.3f} "
            f"{c.get('entity_bonus', 0):>5.2f} "
            f"{(node.title or node.summary or '')[:50]}"
        )

    in_top10 = [g for g in gold_ids if g in [n.id for n in ordered[:10]]]
    print(f"\ngold in top-10: {bool(in_top10)}  gold in top-20: {bool([g for g in gold_ids if g in [n.id for n in ordered]])}")
    if gold_ids and not in_top10:
        for g in gold_ids:
            ranks = [rk for rk, n in enumerate(ordered, start=1) if n.id == g]
            print(f"  gold {g[:8]} at rank: {ranks if ranks else 'NOT IN TOP-20'}")


def main() -> None:
    reset_tmp_dir()

    fixture = load_fixture()

    with mock.patch.object(schema_module, "DB_PATH", DB_PATH), \
         mock.patch("pam.ingestion.pipeline.LOG_PATH", LOG_PATH), \
         mock.patch("pam.retrieval.search.LOG_PATH", LOG_PATH), \
         mock.patch("pam.ingestion.pipeline.summarize", return_value=""), \
         mock.patch("pam.ingestion.pipeline.extract_entities", return_value=[]), \
         mock.patch("pam.ingestion.pipeline.generate_edge_fact", return_value=""), \
         mock.patch("pam.retrieval.query_parser._invoke_llm", side_effect=LLMUnavailableError("missing sdk")):
        conn = get_connection(DB_PATH)
        try:
            initialize(conn)
        finally:
            conn.close()

        print("ingesting 55-item detailed corpus...")
        node_ids = ingest_corpus(fixture)
        print(f"  ingested {len(node_ids)} nodes")

        for target in TARGETS:
            diagnose(target, fixture, node_ids)


if __name__ == "__main__":
    main()
