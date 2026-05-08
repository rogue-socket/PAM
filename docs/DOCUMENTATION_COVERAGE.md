# Documentation Coverage Matrix

This matrix maps maintained repository artifacts to the document that explains them.

The docs set now distinguishes current baseline behavior from intended graph-native behavior where relevant. Coverage here means both kinds of documentation remain attached to the right maintained artifact rather than drifting into disconnected design notes.

## Source Files

| Artifact | Kind | Primary Documentation | Status |
| --- | --- | --- | --- |
| `cli.py` | Root source | `docs/MODULE_CLI.md` | Covered |
| `config.py` | Root source | `docs/MODULE_ROOT.md` | Covered |
| `pam/__init__.py` | Package file | `docs/MODULE_ROOT.md` | Covered |
| `pam/agent_interface.py` | Source module | `docs/MODULE_CLI.md` | Covered |
| `pam/chat_agent.py` | Source module | `docs/MODULE_CLI.md` | Covered |
| `pam/feedback.py` | Source module | `docs/MODULE_LIFECYCLE.md` | Covered |
| `pam/lifecycle.py` | Source module | `docs/MODULE_LIFECYCLE.md` | Covered |
| `pam/relations.py` | Source module | `docs/MODULE_LIFECYCLE.md` | Covered |
| `pam/llm_clients.py` | Source module | `docs/TESTING.md`, `docs/EVAL_SUITES.md` | Covered |
| `pam/db/__init__.py` | Package file | `docs/MODULE_DB.md` | Covered |
| `pam/db/schema.py` | Source module | `docs/MODULE_DB.md` | Covered |
| `pam/db/nodes.py` | Source module | `docs/MODULE_DB.md` | Covered |
| `pam/db/edges.py` | Source module | `docs/MODULE_DB.md` | Covered |
| `pam/db/fts.py` | Source module | `docs/MODULE_DB.md` | Covered |
| `pam/ingestion/__init__.py` | Package file | `docs/MODULE_INGESTION.md` | Covered |
| `pam/ingestion/normalize.py` | Source module | `docs/MODULE_INGESTION.md` | Covered |
| `pam/ingestion/extract.py` | Source module | `docs/MODULE_INGESTION.md` | Covered |
| `pam/ingestion/llm.py` | Source module | `docs/MODULE_INGESTION.md` | Covered |
| `pam/ingestion/entity_linker.py` | Source module | `docs/MODULE_INGESTION.md` | Covered |
| `pam/ingestion/pipeline.py` | Source module | `docs/MODULE_INGESTION.md` | Covered |
| `pam/retrieval/__init__.py` | Package file | `docs/MODULE_RETRIEVAL.md` | Covered |
| `pam/retrieval/query_parser.py` | Source module | `docs/MODULE_RETRIEVAL.md` | Covered |
| `pam/retrieval/graph_expander.py` | Source module | `docs/MODULE_RETRIEVAL.md` | Covered |
| `pam/retrieval/ranker.py` | Source module | `docs/MODULE_RETRIEVAL.md` | Covered |
| `pam/retrieval/search.py` | Source module | `docs/MODULE_RETRIEVAL.md` | Covered |
| `scripts/run_copilot_cli_eval.py` | Evaluation utility script | `docs/CODE_INDEX.md` | Covered |
| `scripts/run_all_copilot_evals.py` | Evaluation utility script | `docs/CODE_INDEX.md` | Covered |

## Test Files And Fixtures

| Artifact | Kind | Primary Documentation | Status |
| --- | --- | --- | --- |
| `tests/test_cli.py` | Test module | `docs/TESTING.md` | Covered |
| `tests/test_chat_agent.py` | Test module | `docs/TESTING.md` | Covered |
| `tests/test_db.py` | Test module | `docs/TESTING.md` | Covered |
| `tests/test_deterministic_fallback.py` | Test module | `docs/TESTING.md` | Covered |
| `tests/test_ingestion.py` | Test module | `docs/TESTING.md` | Covered |
| `tests/test_lifecycle.py` | Test module | `docs/TESTING.md` | Covered |
| `tests/test_llm_clients.py` | Test module | `docs/TESTING.md` | Covered |
| `tests/test_relations.py` | Test module | `docs/TESTING.md` | Covered |
| `tests/test_retrieval.py` | Test module | `docs/TESTING.md` | Covered |
| `tests/test_copilot_cli_eval.py` | Test module | `docs/TESTING.md` | Covered |
| `tests/test_detailed_agent_eval.py` | Evaluation test module | `docs/TESTING.md` | Covered |
| `tests/test_large_agent_eval.py` | Evaluation test module | `docs/TESTING.md` | Covered |
| `tests/test_hard_agent_eval.py` | Evaluation test module | `docs/TESTING.md` | Covered |
| `tests/hard_agent_eval_fixture.py` | Evaluation fixture builder | `docs/TESTING.md` | Covered |
| `tests/regression_eval_fixture.py` | Evaluation fixture adapter | `docs/TESTING.md`, `docs/EVAL_SUITES.md` | Covered |
| `tests/irl_eval_fixture.py` | Evaluation fixture loader | `docs/TESTING.md`, `docs/EVAL_SUITES.md` | Covered |
| `tests/fixtures/retrieval_regression_corpus.json` | Regression fixture | `docs/TESTING.md`, `docs/EVAL_SUITES.md` | Covered |
| `tests/fixtures/large_agent_eval_corpus.json` | Evaluation fixture | `docs/TESTING.md`, `docs/EVAL_SUITES.md` | Covered |
| `tests/fixtures/irl_eval_corpus.json` | Evaluation fixture (real-world mess) | `docs/TESTING.md`, `docs/EVAL_SUITES.md` | Covered |

## Support And Runtime Artifacts

| Artifact | Kind | Primary Documentation | Status |
| --- | --- | --- | --- |
| `.github/copilot-instructions.md` | Repository instructions file | `docs/REPOSITORY_ARTIFACTS.md` | Covered |
| `.github/skills/pam-memory/SKILL.md` | Skill file | `docs/REPOSITORY_ARTIFACTS.md` | Covered |
| `.github/skills/pam-memory/references/cli-examples.md` | Reference doc | `docs/REPOSITORY_ARTIFACTS.md` | Covered |
| `.gitignore` | Repository ignore rules | `docs/REPOSITORY_ARTIFACTS.md` | Covered |
| `.tmp_manual_cli/detailed_memory_eval/run_detailed_eval.py` | Maintained evaluation support script | `docs/REPOSITORY_ARTIFACTS.md` | Covered |
| `.tmp_manual_cli/detailed_memory_eval/` | Detailed eval workspace and generated output class | `docs/REPOSITORY_ARTIFACTS.md` | Covered |
| `.tmp_manual_cli/*/` | Scratch and manual evaluation workspaces | `docs/REPOSITORY_ARTIFACTS.md` | Covered |
| `pam.db` | Runtime artifact | `docs/REPOSITORY_ARTIFACTS.md` | Covered |
| `pam_log.jsonl` | Runtime artifact | `docs/REPOSITORY_ARTIFACTS.md` | Covered |
| `review_inventory.txt` | Manual repository inventory | `docs/CODE_INDEX.md` | Covered |
| `.venv/` | Environment directory | `docs/REPOSITORY_ARTIFACTS.md` | Covered |
| `__pycache__/` | Generated cache directory | `docs/REPOSITORY_ARTIFACTS.md` | Covered |

## Documentation Files

| Artifact | Kind | Primary Documentation | Status |
| --- | --- | --- | --- |
| `docs/README.md` | Documentation index | `docs/README.md` | Covered |
| `docs/ARCHITECTURE.md` | Documentation | `docs/README.md` | Covered |
| `docs/CODE_INDEX.md` | Documentation | `docs/README.md` | Covered |
| `docs/FLOWS.md` | Documentation | `docs/README.md` | Covered |
| `docs/MODULE_ROOT.md` | Documentation | `docs/README.md` | Covered |
| `docs/MODULE_DB.md` | Documentation | `docs/README.md` | Covered |
| `docs/MODULE_INGESTION.md` | Documentation | `docs/README.md` | Covered |
| `docs/MODULE_RETRIEVAL.md` | Documentation | `docs/README.md` | Covered |
| `docs/MODULE_LIFECYCLE.md` | Documentation | `docs/README.md` | Covered |
| `docs/MODULE_CLI.md` | Documentation | `docs/README.md` | Covered |
| `docs/TESTING.md` | Documentation | `docs/README.md` | Covered |
| `docs/EVAL_SUITES.md` | Documentation (eval-suite cheat sheet) | `docs/README.md` | Covered |
| `docs/EVAL_RESULTS_2026-05-06.md` | Documentation (dated eval run) | `docs/README.md` | Covered |
| `docs/EVAL_REGRESSION_RERUN_2026-05-07.md` | Documentation (dated eval re-run + matcher diagnosis) | `docs/README.md` | Covered |
| `docs/EVAL_RESULTS_2026-05-07.md` | Documentation (full 560-query eval run) | `docs/README.md` | Covered |
| `docs/AUDIT_2026-05-06.md` | Documentation (dated audit) | `docs/README.md` | Covered |
| `CLAUDE.md` | Agent-facing project briefing | `docs/README.md` | Covered |
| `decisions.md` | Agent-facing durable decisions | `CLAUDE.md` § Agent-facing scaffolding | Covered |
| `glossary.md` | Agent-facing project terms | `CLAUDE.md` § Agent-facing scaffolding | Covered |
| `backlog.md` | Agent-facing durable open work | `CLAUDE.md` § Agent-facing scaffolding | Covered |
| `audits/` | Point-in-time audit snapshots (mirrors of `docs/AUDIT_*.md`) | `CLAUDE.md` § Agent-facing scaffolding | Covered |
| `test_findings/` | Point-in-time eval / test findings (mirrors of `docs/EVAL_*.md`) | `CLAUDE.md` § Agent-facing scaffolding | Covered |
| `prds/` | Point-in-time proposal/spec snapshots | `CLAUDE.md` § Agent-facing scaffolding | Covered |
| `misc/` | Worth-keeping notes that don't fit the other folders | `CLAUDE.md` § Agent-facing scaffolding | Covered |
| `docs/EXPLORATORY_EVALUATION.md` | Documentation | `docs/README.md` | Covered |
| `docs/RETRIEVAL_RELATIONS_PLAN.md` | Documentation | `docs/README.md` | Covered |
| `docs/HYBRID_RETRIEVAL_PLAN.md` | Documentation | `docs/README.md` | Covered |
| `docs/REPOSITORY_ARTIFACTS.md` | Documentation | `docs/README.md` | Covered |
| `docs/DEPENDABILITY_PLAN.md` | Documentation | `docs/README.md` | Covered |
| `docs/DOCUMENTATION_COVERAGE.md` | Documentation | `docs/README.md` | Covered |

## Coverage Statement

All maintained source modules, tooling scripts, maintained test modules, evaluation fixtures, maintained support files, and documented artifact classes are covered by the docs set.

Special handling for `.tmp_manual_cli/`:

- `detailed_memory_eval/run_detailed_eval.py` is treated as a maintained support artifact because the detailed evaluation test imports its corpus and query definitions
- generated outputs under `detailed_memory_eval/` are documented at the workspace or artifact-class level because they are local evaluation byproducts, not required checked-in files
- other `.tmp_manual_cli/*/` contents remain documented at the artifact-class level because they are scratch or manual workspaces rather than core product surfaces
