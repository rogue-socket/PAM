# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

PAM (Personal Agent Memory) is a local-first SQLite-backed memory system for personal agents. The intended product is a graph-native memory store; the current code is an FTS-led, relation-aware baseline that is evolving toward graph-first reasoning. When changing behavior, keep the distinction between the **current baseline** and the **intended graph-native implementation** in mind — `docs/ARCHITECTURE.md` and `docs/RETRIEVAL_RELATIONS_PLAN.md` are authoritative on this split.

## Commands

There is no `pyproject.toml` / `requirements.txt` in the repo. Activate the project's conda env before running anything (per global Python rules). The repo uses `click` for the CLI and `pytest` for tests.

CLI entry point (`cli.py` at repo root):

- `python cli.py add "..."` / `--url` / `--file` / `--type note` — ingest a memory.
- `python cli.py session start` — emit a new session UUID.
- `python cli.py query "..." [--top N] [--json]` — retrieve.
- `python cli.py chat [QUESTION] [--show-context]` — grounded chat over PAM.
- `python cli.py upvote|downvote|pin|supersede|unarchive|show|list|graph|migrate|stats|decay` — node and lifecycle ops.

Tests:

- `pytest tests/` — full suite.
- `pytest tests/test_retrieval.py::test_name` — single test.
- Heavy eval suites (`test_detailed_agent_eval.py`, `test_large_agent_eval.py`, `test_hard_agent_eval.py`, `test_copilot_cli_eval.py`) call out to live tooling and are slow/flaky — run them only when explicitly evaluating retrieval quality, not as part of normal dev loops.

Useful env vars (see `config.py`):

- `PAM_DB_PATH` (default `pam.db`) — SQLite file.
- `PAM_LOG_PATH` (default `pam_log.jsonl`) — append-only telemetry.

## Architecture

Top-level layout:

- `cli.py` — human CLI; opens a connection and calls `initialize()` before every command.
- `config.py` — all tuning knobs (ranking weights, decay, entity thresholds, LLM provider). Change values here rather than threading parameters through call sites.
- `pam/db/` — schema, nodes, edges, FTS5. Authoritative state. `get_initialized_connection()` and `initialize()` perform versioned migrations + compatibility repair (e.g. backfilling `workspace_id` on older stores).
- `pam/ingestion/` — `pipeline.ingest()` is the one write entry point. It normalizes input, dedupes by `content_hash` within `workspace_id`, optionally calls LLM helpers (`llm.py`) for summary/entities/edge facts, links entities (`entity_linker.py`), and writes provenance / cue-based edges (`DERIVED_FROM`, `SUPERSEDES`, `CONTRADICTS`).
- `pam/retrieval/` — `search.retrieve()` is the read entry point. Pipeline: `query_parser` → FTS candidate selection → `graph_expander` (bounded by `MAX_GRAPH_DEPTH`, `EDGE_WEIGHT_EXPANSION_THRESHOLD`) → `ranker` → `RetrievalResult`. Query parsing has a deterministic fallback that handles ISO dates, `today`/`yesterday`/`this week`, simple relation phrasing — the LLM path is optional.
- `pam/lifecycle.py` — exponential decay over `updated_at` with archive threshold.
- `pam/feedback.py` — upvote/downvote/pin/supersede mutations. Supersession writes a `SUPERSEDES` edge and dampens the old node's importance.
- `pam/agent_interface.py` — stable surface for agents: `ingest_for_agent()`, `query_for_agent()`, `format_for_context_window()`. Prefer this over reaching into modules directly when writing agent code.
- `pam/chat_agent.py` — grounded answer generation that wraps retrieval.

### Core invariants (do not break)

- Public entry points (`cli.py` commands, `retrieve()`, `ingest()`) initialize schema before doing useful work — fresh-DB bootstrap is part of the normal contract, not a separate operator step.
- Every node carries a first-class `workspace_id` (resolved CWD by default). Dedupe and entity linking are scoped to it.
- FTS stays in sync via SQLite triggers — do not dual-write `fts_index` from Python.
- `access_count` is incremented on retrieval; `updated_at` is **not** refreshed by reads (decay depends on this).
- Decay uses `updated_at`; recency filtering and ranking use `valid_at`. Don't confuse them.
- Foreign keys are on; create main nodes before edges.
- Deterministic fallback is a hard requirement: ingest and query parsing must keep working when LLM SDKs are missing or fail. Don't add LLM-only code paths.

### Node and edge model

- Node types: `event`, `note`, `entity`, `source`. Statuses: `active`, `draft`, `reference`, `archived`. Draft entities are graph bridges but are not surfaced as direct results.
- Edge relations in use: `REFERS_TO` (note/event → entity), `DERIVED_FROM` (note → source), `RELATED`, `CONTRADICTS`, `SUPERSEDES`. Treat this set as a dependable minimum — adding new relation kinds requires write-time rules dependable enough to maintain graph quality.

### Retrieval result contract

`RetrievalResult` (see `pam/retrieval/ranker.py`) exposes node buckets (`events`, `entities`, `notes`, `sources`), `relationships`, `conflicts`, `superseded`, `edge_facts`, `graph_explanations`, `session_groups`, `query_meta`, `ordered_nodes`. CLI/agent renderers should use these fields explicitly rather than flattening into prose.

## Working rules from `.github/copilot-instructions.md`

- Do not read or mutate `pam.db` directly — go through the CLI or `pam.agent_interface`.
- For PAM-grounded answers, query PAM first; if results don't support a confident answer, say so rather than guessing.
- For evaluations, keep CWD at the repo root so workspace scoping is stable, and use `PAM_DB_PATH` / `PAM_LOG_PATH` for isolated evaluation state.

## Documentation

`docs/` is the source of truth for design intent. Most relevant when changing behavior:

- `docs/ARCHITECTURE.md` — current vs. intended split, invariants, ranking model.
- `docs/RETRIEVAL_RELATIONS_PLAN.md` — roadmap from relation-aware to graph-native retrieval.
- `docs/MODULE_*.md` — per-module current behavior + what's missing.
- `docs/DOCUMENTATION_COVERAGE.md` — file-to-doc mapping. When you add/rename/remove a maintained file, update the relevant module doc and this coverage matrix.
