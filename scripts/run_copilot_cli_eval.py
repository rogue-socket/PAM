from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
from contextlib import ExitStack
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = ROOT / "cli.py"
TEMP_ROOT = ROOT / ".tmp_manual_cli" / "copilot_cli_eval"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


BACKENDS = ("copilot", "claude")
DEFAULT_BACKEND = "claude"
DEFAULT_MODEL_BY_BACKEND = {
    "copilot": "claude-sonnet-4.5",
    "claude": "claude-sonnet-4-5",
}


def _find_copilot_command_prefix() -> tuple[str, ...]:
    """Locate the GitHub Copilot CLI executable across platforms.

    macOS / Linux first via PATH; Windows-specific lookups gated by
    sys.platform. Raises FileNotFoundError if no candidate exists.
    """
    on_path = shutil.which("copilot")
    if on_path:
        return (on_path,)

    if sys.platform == "win32":
        appdata = Path(os.getenv("APPDATA", ""))
        npm_loader = appdata / "npm" / "node_modules" / "@github" / "copilot" / "npm-loader.js"
        node_exe = shutil.which("node")
        if node_exe and npm_loader.exists():
            return (node_exe, str(npm_loader))

        candidates = (
            shutil.which("copilot.cmd"),
            str(appdata / "npm" / "copilot.cmd"),
            str(
                appdata
                / "Code"
                / "User"
                / "globalStorage"
                / "github.copilot-chat"
                / "copilotCli"
                / "copilot.bat"
            ),
        )
        for candidate in candidates:
            if candidate and Path(candidate).exists():
                return (candidate,)

    raise FileNotFoundError("Could not locate the GitHub Copilot CLI executable")


@lru_cache(maxsize=1)
def _get_copilot_command_prefix() -> tuple[str, ...]:
    """Cached, lazy resolver for the Copilot CLI command prefix."""
    return _find_copilot_command_prefix()


def _find_claude_command_prefix() -> tuple[str, ...]:
    """Locate the Claude Code CLI executable. Same contract as Copilot."""
    on_path = shutil.which("claude")
    if on_path:
        return (on_path,)
    raise FileNotFoundError("Could not locate the Claude Code CLI executable (`claude`)")


@lru_cache(maxsize=1)
def _get_claude_command_prefix() -> tuple[str, ...]:
    return _find_claude_command_prefix()


SUITE_SPECS = {
    "detailed": {
        "module": "tests.test_detailed_agent_eval",
        "loader": "load_detailed_eval_fixture",
        "label": "DetailedAgentEvaluationSuiteTests",
    },
    "large": {
        "module": "tests.test_large_agent_eval",
        "loader": "load_large_eval_fixture",
        "label": "LargeAgentEvaluationSuiteTests",
    },
    "hard": {
        "module": "tests.test_hard_agent_eval",
        "loader": "load_hard_eval_fixture",
        "label": "HardAgentEvaluationSuiteTests",
    },
    "regression": {
        "module": "tests.regression_eval_fixture",
        "loader": "load_regression_eval_fixture",
        "label": "RetrievalRegressionEvalSuite",
    },
    "irl": {
        "module": "tests.irl_eval_fixture",
        "loader": "load_irl_eval_fixture",
        "label": "IRLAgentEvaluationSuite",
    },
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate PAM end-to-end via a real LLM backend (Copilot CLI or Claude Code CLI).",
    )
    parser.add_argument("--suite", choices=sorted(SUITE_SPECS), required=True)
    parser.add_argument(
        "--backend",
        choices=BACKENDS,
        default=DEFAULT_BACKEND,
        help=f"Which CLI backend to grade against. Default: {DEFAULT_BACKEND}.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model ID to pass to the backend. Default depends on backend.",
    )
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--max-queries", type=int, default=None)
    parser.add_argument(
        "--start-from",
        type=int,
        default=1,
        help="1-based query index to start at. Useful for resuming after a rate-limit truncation.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Print a batch summary to stderr every N queries. Runs all at once if omitted.",
    )
    parser.add_argument("--include-misses", action="store_true")
    args = parser.parse_args()
    if args.model is None:
        args.model = DEFAULT_MODEL_BY_BACKEND[args.backend]
    return args


def _load_fixture(suite_name: str) -> tuple[dict, str]:
    spec = SUITE_SPECS[suite_name]
    module = importlib.import_module(spec["module"])
    fixture = getattr(module, spec["loader"])()
    return fixture, spec["label"]


def _eval_paths(suite_name: str) -> tuple[Path, Path, Path]:
    eval_root = TEMP_ROOT / suite_name
    if eval_root.exists():
        shutil.rmtree(eval_root)
    link_dir = eval_root / "link_sources"
    link_dir.mkdir(parents=True, exist_ok=True)
    return eval_root, eval_root / "pam.db", eval_root / "pam_log.jsonl"


def _ingest_fixture(fixture: dict, *, db_path: Path, log_path: Path, link_dir: Path) -> None:
    from pam.agent_interface import ingest_for_agent
    from pam.db.schema import get_connection, initialize
    from pam.feedback import supersede

    node_ids: dict[str, str] = {}

    with ExitStack() as stack:
        stack.enter_context(mock.patch("pam.ingestion.pipeline.summarize", return_value=""))
        stack.enter_context(mock.patch("pam.ingestion.pipeline.extract_entities", return_value=[]))
        stack.enter_context(mock.patch("pam.ingestion.pipeline.generate_edge_fact", return_value=""))

        conn = get_connection(db_path)
        try:
            initialize(conn)
        finally:
            conn.close()

        for item in fixture["corpus"]:
            valid_at = datetime.fromisoformat(item["at"]).replace(tzinfo=timezone.utc)
            parent_note_id = None
            if item.get("derived_from"):
                parent_note_id = node_ids[item["derived_from"]]

            if item["ingest_kind"] == "url":
                source_path = link_dir / item["filename"]
                source_path.write_text(item["text"], encoding="utf-8")
                result = ingest_for_agent(
                    source_path.resolve().as_uri(),
                    session_id=item["session"],
                    valid_at=valid_at,
                    workspace_id=ROOT,
                    parent_note_id=parent_note_id,
                )
            elif item["ingest_kind"] == "file":
                result = ingest_for_agent(
                    item["text"],
                    kind="source",
                    session_id=item["session"],
                    valid_at=valid_at,
                    workspace_id=ROOT,
                    parent_note_id=parent_note_id,
                )
            elif item["ingest_kind"] == "event":
                result = ingest_for_agent(
                    item["text"],
                    kind="event",
                    session_id=item["session"],
                    valid_at=valid_at,
                    workspace_id=ROOT,
                )
            else:
                result = ingest_for_agent(
                    item["text"],
                    kind="note",
                    session_id=item["session"],
                    valid_at=valid_at,
                    workspace_id=ROOT,
                )

            node_ids[item["key"]] = result.node_id

        conn = get_connection(db_path)
        try:
            for old_key, new_key in fixture["supersedes"]:
                if not supersede(conn, node_ids[new_key], node_ids[old_key]):
                    raise RuntimeError(f"Failed to supersede {old_key} -> {new_key}")
        finally:
            conn.close()


def _compact_text(text: str) -> str:
    return " ".join(text.split())


def _truncate_text(text: str, limit: int) -> str:
    compact = _compact_text(text)
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 3)].rstrip() + "..."


# Keep the eval renderer separate from pam.agent_interface so benchmark prompts
# stay stable and continue to expose raw ids for debugging score regressions.
def _render_retrieval_context(result) -> str:
    lines = ["Retrieved PAM results:"]
    budget = 5000

    title_by_id: dict[str, str] = {}
    for node in result.ordered_nodes:
        label = (node.title or node.id).strip() or node.id
        title_by_id[node.id] = label

    if result.relationships:
        lines.append("")
        lines.append("Relationships:")
        for edge in result.relationships[:10]:
            fact = (edge.fact or "").strip()
            # PAM stores DERIVED_FROM as parent_note -> derived_source, which reads
            # backwards from natural English ("A DERIVED_FROM B" = A came from B).
            # Swap endpoints at the render so the line matches its semantic.
            if edge.relation == "DERIVED_FROM":
                src_id, tgt_id = edge.target_id, edge.source_id
            else:
                src_id, tgt_id = edge.source_id, edge.target_id
            src_label = title_by_id.get(src_id, src_id)
            tgt_label = title_by_id.get(tgt_id, tgt_id)
            relation_line = f'- "{src_label}" {edge.relation} "{tgt_label}"'
            if fact:
                relation_line += f" | {fact}"
            candidate = "\n".join([*lines, relation_line])
            if len(candidate) > budget:
                lines.append("[truncated]")
                return "\n".join(lines)
            lines.append(relation_line)

    node_groups = (
        ("Events", result.events),
        ("Notes", result.notes),
        ("Sources", result.sources),
        ("Entities", result.entities),
    )
    for section_title, nodes in node_groups:
        materialized = list(nodes)
        if not materialized:
            continue

        section_lines = ["", f"{section_title}:"]
        for node in materialized:
            title = (node.title or node.id).strip()
            summary = (node.summary or "").strip()
            content = (node.content or "").strip()

            section_lines.append(f"- {title} ({node.valid_at.date().isoformat()})")
            if summary:
                section_lines.append(f"  summary: {_truncate_text(summary, 220)}")
            if content:
                section_lines.append(f"  content: {_truncate_text(content, 420)}")

            candidate = "\n".join([*lines, *section_lines])
            if len(candidate) > budget:
                lines.append("[truncated]")
                return "\n".join(lines)

        lines.extend(section_lines)

    return "\n".join(lines)


def _retrieve_context(raw_query: str, *, top_k: int) -> str:
    from pam.agent_interface import query_for_agent

    result = query_for_agent(raw_query, top_k=top_k, workspace_id=ROOT)
    return _render_retrieval_context(result)


def _prompt_for_answer(raw_query: str, retrieved_context: str) -> str:
    return (
        "Answer the user's question using only the PAM retrieval result provided below.\n"
        f"Question: {raw_query}\n\n"
        "Rules:\n"
        "- Do not use outside knowledge.\n"
        "- Do not inspect fixture files, source corpora, or test code.\n"
        "- Do not ask clarifying questions. You already have the full question.\n"
        "- Base the final answer only on the PAM retrieval result below.\n"
        "- The PAM context is the user's own memory log. 'I', 'me', 'my', 'we', and 'us' in the context refer to the user; events like 'X shadowed me' or 'X reviewed my Z' are activities the user participated in.\n"
        "- If the retrieval result does not support an answer, reply exactly with NO_ANSWER.\n"
        "- Output only the final answer text.\n\n"
        "PAM retrieval context:\n"
        f"{retrieved_context}"
    )


def _run_copilot_query(raw_query: str, *, model: str, top_k: int, db_path: Path, log_path: Path) -> str:
    retrieved_context = _retrieve_context(raw_query, top_k=top_k)

    command = [
        *_get_copilot_command_prefix(),
        "-p",
        _prompt_for_answer(raw_query, retrieved_context),
        "--model",
        model,
        "--no-ask-user",
        "--stream",
        "off",
        "-s",
        "--output-format",
        "text",
    ]

    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=os.environ.copy(),
            capture_output=True,
            timeout=300,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"copilot query timed out after 300s: {raw_query}") from exc

    stdout = completed.stdout.decode("utf-8", errors="replace").strip()
    stderr = completed.stderr.decode("utf-8", errors="replace").strip()
    if completed.returncode != 0:
        raise RuntimeError(stderr or stdout or f"copilot exited with code {completed.returncode}")
    return stdout


def _run_claude_query(raw_query: str, *, model: str, top_k: int, db_path: Path, log_path: Path) -> str:
    """Eval via Claude Code CLI (`claude -p`).

    Same retrieval + prompt as Copilot; only the binary and the flag set
    differ. Output format is plain text so the answer-pass matcher works
    unchanged.
    """
    retrieved_context = _retrieve_context(raw_query, top_k=top_k)

    command = [
        *_get_claude_command_prefix(),
        "-p",
        _prompt_for_answer(raw_query, retrieved_context),
        "--model",
        model,
        "--output-format",
        "text",
    ]

    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=os.environ.copy(),
            capture_output=True,
            timeout=300,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"claude query timed out after 300s: {raw_query}") from exc

    stdout = completed.stdout.decode("utf-8", errors="replace").strip()
    stderr = completed.stderr.decode("utf-8", errors="replace").strip()
    if completed.returncode != 0:
        raise RuntimeError(stderr or stdout or f"claude exited with code {completed.returncode}")
    return stdout


def _run_backend_query(
    backend: str,
    raw_query: str,
    *,
    model: str,
    top_k: int,
    db_path: Path,
    log_path: Path,
) -> str:
    if backend == "copilot":
        return _run_copilot_query(raw_query, model=model, top_k=top_k, db_path=db_path, log_path=log_path)
    if backend == "claude":
        return _run_claude_query(raw_query, model=model, top_k=top_k, db_path=db_path, log_path=log_path)
    raise ValueError(f"unknown backend: {backend!r}")


def _normalize_answer_text(answer: str) -> str:
    normalized = " ".join(answer.strip().split())
    normalized = re.sub(r"^[\s\-\*\u2022\u25cf]+", "", normalized)
    normalized = normalized.strip("`*_\"' ")
    return normalized


def _canonicalize_match_text(text: str) -> str:
    canonical = _normalize_answer_text(text).lower()
    # Strip inline markdown emphasis that LLM answers tend to wrap around code
    # tokens (`--json`, `valid_at`) and bold key terms (**source**). These are
    # presentation, not content, but they break naive substring matching.
    canonical = canonical.replace("`", "").replace("**", "").replace("__", "")
    canonical = re.sub(r"(\d)\s+([a-z%]+)\b", r"\1\2", canonical)
    return canonical


_TERSE_ANSWER_MIN_TOKENS = 2


def _answer_passes(answer: str, query_case: dict) -> bool:
    """Bidirectional substring matcher.

    Passes when the canonical expected substring appears in the canonical
    answer (the original strict direction) OR when the canonical answer
    appears in the canonical expected — guards against terse-but-correct
    answers like `"Reykjavik annex"` for an expected `"the Reykjavik annex"`,
    or `"Text relevance"` for an expected verbose policy sentence. The
    reverse direction requires at least `_TERSE_ANSWER_MIN_TOKENS` tokens to
    avoid trivial matches like the literal word `"the"`.
    """
    normalized = _normalize_answer_text(answer)
    if query_case.get("expect_empty"):
        return normalized.upper() == "NO_ANSWER"

    canonical_answer = _canonicalize_match_text(normalized)
    answer_tokens = canonical_answer.split()

    for expected in query_case.get("expected_substrings", []):
        canonical_expected = _canonicalize_match_text(expected)
        if not canonical_expected:
            continue
        if canonical_expected in canonical_answer:
            return True
        if (
            len(answer_tokens) >= _TERSE_ANSWER_MIN_TOKENS
            and canonical_answer in canonical_expected
        ):
            return True
    return False


def _log(msg: str) -> None:
    """Write a progress line to stderr so it appears even when stdout is piped."""
    print(msg, file=sys.stderr, flush=True)


def _batch_summary(summary: dict, batch_label: str) -> dict:
    score = summary["overall_hits"] / summary["overall_total"] * 100.0 if summary["overall_total"] else 0.0
    return {
        "batch": batch_label,
        "hits": summary["overall_hits"],
        "total": summary["overall_total"],
        "score": round(score, 2),
        "query_type_hits": dict(summary["query_type_hits"]),
        "query_type_totals": dict(summary["query_type_totals"]),
        "miss_count": len(summary["misses"]),
    }


def _evaluate_queries(
    fixture: dict,
    *,
    backend: str = "copilot",
    model: str,
    top_k: int,
    db_path: Path,
    log_path: Path,
    max_queries: int | None,
    batch_size: int | None,
    start_from: int = 1,
) -> dict:
    summary = {
        "overall_hits": 0,
        "overall_total": 0,
        "overall_score": 0.0,
        "query_type_hits": {},
        "query_type_totals": {},
        "misses": [],
        "transcript": [],
    }

    all_queries = fixture["queries"]
    if max_queries is not None:
        all_queries = all_queries[:max_queries]
    start_index = max(1, start_from)
    query_cases = all_queries[start_index - 1 :]

    total_queries = len(all_queries)
    _log(
        f"[eval] starting {len(query_cases)} queries (indices {start_index}..{total_queries}) "
        f"via backend={backend} model={model} batch_size={batch_size or len(query_cases)}"
    )

    for offset, query_case in enumerate(query_cases):
        index = start_index + offset
        query_type = query_case["query_type"]
        summary["query_type_totals"].setdefault(query_type, 0)
        summary["query_type_hits"].setdefault(query_type, 0)
        summary["query_type_totals"][query_type] += 1
        summary["overall_total"] += 1

        short_query = query_case["query"][:80]
        _log(f"[eval] [{index}/{total_queries}] ({query_type}) {short_query}...")

        error_message = None
        try:
            answer = _run_backend_query(
                backend,
                query_case["query"],
                model=model,
                top_k=top_k,
                db_path=db_path,
                log_path=log_path,
            )
        except RuntimeError as exc:
            error_message = str(exc)
            answer = f"[ERROR] {error_message}"

        passed = _answer_passes(answer, query_case)
        if passed:
            summary["overall_hits"] += 1
            summary["query_type_hits"][query_type] += 1
            _log(f"[eval] [{index}/{total_queries}] => PASS")
        else:
            short_answer = _normalize_answer_text(answer)[:120]
            _log(f"[eval] [{index}/{total_queries}] => MISS  answer={short_answer}")
            miss = {
                "index": index,
                "query_type": query_type,
                "query": query_case["query"],
                "answer": answer,
            }
            if error_message is not None:
                miss["error"] = error_message
            summary["misses"].append(miss)

        entry = {
            "index": index,
            "query_type": query_type,
            "query": query_case["query"],
            "answer": answer,
            "passed": passed,
        }
        if error_message is not None:
            entry["error"] = error_message
        summary["transcript"].append(entry)

        # Emit batch summary after every batch_size queries
        if batch_size and index % batch_size == 0:
            batch_label = f"queries {index - batch_size + 1}-{index}"
            batch_info = _batch_summary(summary, batch_label)
            _log(f"[batch] {json.dumps(batch_info)}")

    # Final partial-batch summary if there's a remainder
    if batch_size and total_queries % batch_size != 0:
        last_batch_start = (total_queries // batch_size) * batch_size + 1
        batch_label = f"queries {last_batch_start}-{total_queries}"
        batch_info = _batch_summary(summary, batch_label)
        _log(f"[batch] {json.dumps(batch_info)}")

    if summary["overall_total"]:
        summary["overall_score"] = summary["overall_hits"] / summary["overall_total"] * 100.0

    _log(f"[eval] done: {summary['overall_hits']}/{summary['overall_total']} = {summary['overall_score']:.1f}%")
    return summary


def main() -> int:
    args = _parse_args()
    eval_root, db_path, log_path = _eval_paths(args.suite)
    link_dir = eval_root / "link_sources"

    os.environ["PAM_DB_PATH"] = str(db_path)
    os.environ["PAM_LOG_PATH"] = str(log_path)

    fixture, label = _load_fixture(args.suite)

    started_at = datetime.now(timezone.utc)
    _log(f"[eval] ingesting {len(fixture['corpus'])} corpus items...")
    _ingest_fixture(fixture, db_path=db_path, log_path=log_path, link_dir=link_dir)
    _log(f"[eval] ingestion complete. starting evaluation.")
    summary = _evaluate_queries(
        fixture,
        backend=args.backend,
        model=args.model,
        top_k=args.top_k,
        db_path=db_path,
        log_path=log_path,
        max_queries=args.max_queries,
        batch_size=args.batch_size,
        start_from=args.start_from,
    )
    finished_at = datetime.now(timezone.utc)

    full_payload = {
        "suite": label,
        "backend": args.backend,
        "model": args.model,
        "top_k": args.top_k,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "db_path": str(db_path),
        "log_path": str(log_path),
        "summary": summary,
    }

    transcript_dir = ROOT / "test_findings" / "eval_runs"
    transcript_dir.mkdir(parents=True, exist_ok=True)
    transcript_name = (
        f"{started_at.strftime('%Y-%m-%d_%H-%M-%S')}_{args.suite}_{args.backend}.json"
    )
    transcript_path = transcript_dir / transcript_name
    transcript_path.write_text(
        json.dumps(full_payload, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )
    _log(f"[eval] transcript written to {transcript_path.relative_to(ROOT)}")

    if args.include_misses:
        stdout_payload = full_payload
    else:
        stdout_summary = {
            **summary,
            "misses": summary["misses"][:10],
            "transcript": [],
        }
        stdout_payload = {**full_payload, "summary": stdout_summary}
    print(json.dumps(stdout_payload, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())