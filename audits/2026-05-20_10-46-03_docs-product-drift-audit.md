# Docs ↔ Product Drift Audit — 2026-05-20

## Scope

Line-by-line comparison of every maintained doc against the actual code, to find
and eliminate places where the docs describe behavior the product no longer has
(or has gained). Covered: `docs/ARCHITECTURE.md`, all five `MODULE_*.md`,
`FLOWS.md`, `EVAL_SUITES.md`, `TESTING.md`, `CODE_INDEX.md`,
`DOCUMENTATION_COVERAGE.md`, the three plan docs, plus root `CLAUDE.md` and
`glossary.md`. Dated snapshot docs (`AUDIT_*`, `EVAL_RESULTS_*`,
`EVAL_REGRESSION_RERUN_*`, `EXPLORATORY_EVALUATION.md`) were intentionally left
untouched — they are point-in-time records, not maintained reference.

## Method

Five parallel read-only investigators (one per code area: db / ingestion /
retrieval / cli+lifecycle+root / test+meta docs) reported drift findings against
their owning code. Cross-cutting docs were verified directly. Every function name
written into a doc was grep-confirmed against the code before finalizing.

## Drift found and fixed — by theme

1. **Vector / embedding retrieval shipped but documented as future.** `vector_search()`,
   the sqlite-vec `vec_nodes` table, `pam/embeddings.py`, the `WEIGHT_VEC_SIMILARITY`
   ranking term, and `score_components.vector_similarity` are all live. ARCHITECTURE,
   glossary ("FTS is PAM's only channel"), CLAUDE.md's pipeline line, FLOWS query
   flow, MODULE_RETRIEVAL, MODULE_ROOT, RETRIEVAL_RELATIONS_PLAN, and
   HYBRID_RETRIEVAL_PLAN all described it as not-yet-built. `score_components` is
   **five** components, not four (glossary + MODULE_RETRIEVAL said four).
2. **Schema is at v2; docs said v1.** ARCHITECTURE said "migrations stop at v1";
   MODULE_DB omitted `transaction.py` and the v2 vec-table migration entirely.
3. **`doctor` + `rebuild-fts` CLI commands undocumented.** ARCHITECTURE, MODULE_CLI,
   and FLOWS missed them — FLOWS explicitly asserted "there is no `doctor` command."
   DEPENDABILITY_PLAN listed operator health tooling as an unimplemented gap.
4. **`transaction()` atomic rollback shipped; docs described manual node-deletion
   cleanup.** MODULE_INGESTION §7.2 and FLOWS ingest step 15. DEPENDABILITY_PLAN
   listed transaction boundaries as an unimplemented gap.
5. **IRL eval corpus grew 38 → 68 queries** with 4 new categories
   (`colloquial_relationship`, `paraphrase`, `time_vague`, `entity_by_role`).
   EVAL_SUITES (table, header, category breakdown) and TESTING were stale.
6. **6 test files + 3 source modules** (`embeddings.py`, `telemetry.py`,
   `db/transaction.py`) were missing from CODE_INDEX / TESTING /
   DOCUMENTATION_COVERAGE — which still claimed "100% coverage." New
   `MODULE_ROOT.md` sections were added for `embeddings.py` and `telemetry.py` so
   the coverage claim is honest again.
7. **Assorted signature / config-key drift.** `score()` /  `rank_and_assemble()`
   missing their vector params; `ParsedQuery` missing `time_range_relative`;
   MODULE_ROOT missing 6 retrieval constants and 2 OpenAI model keys; ranking
   weights documented as "sum to 1.0" (actually 1.10); `ELIGIBLE_STATUSES`
   documented as a set (it is a tuple); `check_database_health()` documented as
   "never raises" (it does — `_check_health_once()` is what suppresses).

17 docs were edited; the plan docs got status banners / "Resolved" markers rather
than rewrites so the original design rationale is preserved.

## Deliberately NOT changed (not doc drift — flagged for follow-up)

- **Regression eval corpus is stale on ranking weights.**
  `tests/fixtures/retrieval_regression_corpus.json` contains the article line
  "Ranking weights favor text relevance more than recency and importance" and a
  query "Which ranking signal has the highest weight?". Post hybrid-split,
  `WEIGHT_TEXT_RELEVANCE` (0.30) is **tied** with `WEIGHT_RECENCY` (0.30) — there
  is no single highest weight. EVAL_SUITES.md was annotated to note this; the
  corpus itself is eval gold data and was left for the owner to decide
  (changing it changes what the eval measures).
- **Dead parameter in `entity_linker.py`.** `link_entities_detailed()` /
  `link_entities()` accept a `content` parameter that is `del`-eted on the first
  line. MODULE_INGESTION now notes it is unused; the code was left as-is (not
  part of this task's scope).

## Files changed

`CLAUDE.md`, `glossary.md`, and under `docs/`: `ARCHITECTURE.md`,
`MODULE_DB.md`, `MODULE_INGESTION.md`, `MODULE_RETRIEVAL.md`, `MODULE_CLI.md`,
`MODULE_LIFECYCLE.md`, `MODULE_ROOT.md`, `FLOWS.md`, `EVAL_SUITES.md`,
`TESTING.md`, `CODE_INDEX.md`, `DOCUMENTATION_COVERAGE.md`,
`DEPENDABILITY_PLAN.md`, `HYBRID_RETRIEVAL_PLAN.md`, `RETRIEVAL_RELATIONS_PLAN.md`.
