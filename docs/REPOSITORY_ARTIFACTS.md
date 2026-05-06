# Repository Artifacts

## Purpose

Not every important repository artifact is a Python module. This document covers maintained support files, maintained evaluation inputs, generated output classes, runtime state, and tool-managed folders so repository coverage matches the working tree that PAM actually uses.

The updated documentation stance matters here too: generated artifacts can be useful evidence, but they are not proof that the intended graph-native personal-memory behavior is implemented. Only current code and maintained tests carry that weight.

## Support Files

### `.github/copilot-instructions.md`

Purpose:

- stores repository-local working rules for Copilot and other coding agents.

Key role in the repo:

- reinforces the CLI-first boundary for PAM by steering agents toward `cli.py` and `pam.agent_interface` instead of direct database access.
- captures the current-versus-intended documentation stance that matters during the graph-native transition.

### `.gitignore`

Purpose:

- keeps runtime databases, local logs, cache files, and disposable evaluation output out of source control.

Key role in the repo:

- preserves the distinction between maintained repository inputs and local generated state.
- makes it explicit that scratch eval outputs under `.tmp_manual_cli/` are optional byproducts, not core authored artifacts.

### `.github/skills/pam-memory/SKILL.md`

Purpose:

- documents how GitHub Copilot should use the PAM CLI for ingestion and retrieval tasks.

Key role in the repo:

- acts as the repository-local skill contract for CLI-first PAM usage.
- points operators and agents at the supported session, add, and query flows.

### `.github/skills/pam-memory/references/cli-examples.md`

Purpose:

- stores reusable CLI examples for ingest and query operations.

Key role in the repo:

- gives concrete command patterns for notes, files, URLs, and JSON queries.
- defines the expected high-level output shape that agents should inspect.

## Maintained Evaluation Inputs And Generated Output Classes

### `.tmp_manual_cli/detailed_memory_eval/run_detailed_eval.py`

Purpose:

- checked-in detailed evaluation script that defines the `CORPUS`, `QUERIES`, and `SUPERSEDES` fixture data used by the detailed agent evaluation suite.

Key role in the repo:

- is imported by `tests/test_detailed_agent_eval.py`, so this file is not just an ad hoc scratch script.
- acts as the authored source for the 55-item detailed eval corpus, its 110 natural-language queries, and the current 32 direct plus 78 indirect query split.

### Generated outputs under `.tmp_manual_cli/detailed_memory_eval/`

Purpose:

- local outputs emitted by the detailed evaluation workflow when someone runs or refreshes it.

Key role in the repo:

- can include dataset snapshots, result JSON, summary markdown, or a generated `run/` workspace when the workflow is executed locally.

How to interpret them:

- helpful for exploratory analysis and result inspection when present.
- disposable compared with source modules and test assertions.
- not required checked-in assets; the current tree may contain only the maintained fixture script plus caches.
- not the canonical definition of PAM behavior and not evidence that PAM already satisfies the intended graph-native reasoning contract.

### Other `.tmp_manual_cli/` subtrees

Purpose:

- workspace-local scratch directories for manual retrieval experiments, casual user evals, Copilot eval passes, and temporary test state.

How to interpret them:

- most of this tree is exploratory or generated state
- many of these subtrees capture useful manual experiments around retrieval quality, personas, or graph behavior
- the important exception is the checked-in detailed eval fixture under `.tmp_manual_cli/detailed_memory_eval/run_detailed_eval.py`

## Runtime State

### `pam.db`

Purpose:

- SQLite database generated or updated at runtime.

Documentation source:

- schema and lifecycle behavior are documented in [ARCHITECTURE.md](./ARCHITECTURE.md), [MODULE_DB.md](./MODULE_DB.md), and [MODULE_LIFECYCLE.md](./MODULE_LIFECYCLE.md).

Maintenance note:

- generated state, not hand-maintained source.

### `pam_log.jsonl`

Purpose:

- append-only runtime telemetry log written by ingestion, retrieval, lifecycle, and feedback flows.

Interpretation:

- useful for debugging, evaluation, and local inspection
- not authoritative for committed application state
- may omit events for operations that roll back before telemetry is written
- should not be treated as proof that a graph-native answer was correct just because a query event was logged

Documentation source:

- log-producing flows are documented in [ARCHITECTURE.md](./ARCHITECTURE.md), [FLOWS.md](./FLOWS.md), and subsystem module docs.

### `.tmp_manual_cli/pam.db`
### `.tmp_manual_cli/pam_log.jsonl`

Purpose:

- scratch database and telemetry log used by manual CLI experiments under the `.tmp_manual_cli` tree.

Interpretation:

- same storage and logging model as the root runtime files, but scoped to exploratory eval work.
- safe to treat as disposable local state.

## Environment Folders

### `.venv/`

Purpose:

- Python virtual environment for local development and tests.

Documentation note:

- tool-managed environment content, not repository-authored logic.

### `__pycache__/`

Purpose:

- Python bytecode cache.

Documentation note:

- generated by interpreter execution.

## Why These Artifacts Are Documented Separately

The main module documents focus on authored logic. This document covers the remaining repository artifacts, including the checked-in eval fixture outside `tests/`, so documentation coverage includes the full repository surface PAM relies on in practice.

It also draws a line between:

- maintained source and maintained test fixtures
- generated historical output
- disposable scratch state

That distinction is important now that the docs explicitly describe both the current implementation and the intended graph-native product direction.
