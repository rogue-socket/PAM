# Testing Documentation

## Purpose Of The Test Suite

The test suite exists to prove two different things at once:

- the current code works as implemented
- the repository has a clear path to testing the graph-native personal-memory behavior it is aiming for

Today the suite locks down behavior at six levels:

- CLI and agent integration
- storage contracts
- ingestion behavior
- lifecycle and feedback rules
- retrieval behavior, including a regression corpus
- end-to-end natural-language evaluation with detailed, large, and hard edge-case corpora

The most important stale-doc fix is this: the current suite proves relation-aware retrieval much better than it proves graph-native reasoning. That is not a criticism of the suite. It is a signal about the next evaluation work the repo needs.

## Test Layout

- `tests/test_cli.py`
- `tests/test_copilot_cli_eval.py`
- `tests/test_detailed_agent_eval.py`
- `tests/test_hard_agent_eval.py`
- `tests/test_large_agent_eval.py`
- `tests/hard_agent_eval_fixture.py`
- `tests/test_db.py`
- `tests/test_ingestion.py`
- `tests/test_lifecycle.py`
- `tests/test_relations.py`
- `tests/test_retrieval.py`
- `tests/fixtures/large_agent_eval_corpus.json`
- `tests/fixtures/retrieval_regression_corpus.json`
- `.tmp_manual_cli/detailed_memory_eval/run_detailed_eval.py`

## What The Current Suite Proves Well

### `tests/test_db.py`

This file locks down the storage baseline:

- schema initialization and versioning
- node CRUD round trips
- metadata updates and `updated_at` refresh
- timestamp preservation
- edge CRUD and cascading deletes
- FTS trigger synchronization
- content-hash lookup
- importance and edge-weight clamping
- access count behavior without freshness mutation
- foreign-key enforcement
- idempotent initialization

This matters because a graph-native memory system still depends on boring storage correctness.

### `tests/test_ingestion.py`

This file locks down the write-path baseline:

- normalization rules
- title extraction heuristics
- content hashing and dedupe
- changed URL-content behavior
- workspace-scoped dedupe
- LLM helper fallbacks
- entity linking and entity creation
- `REFERS_TO` edge creation
- end-to-end ingest behavior
- session staleness warnings
- source provenance through `DERIVED_FROM`
- explicit cue-based `DERIVED_FROM` inference between shared-entity notes
- explicit cue-based `SUPERSEDES` inference for revision and replacement phrasing
- explicit cue-based `CONTRADICTS` inference for narrow negation-versus-recommendation cases
- provenance creation even on dedupe hits
- rollback on post-insert failures
- invalid parent-note rejection

This is strong coverage for the current ingest pipeline.

### `tests/test_retrieval.py`

This file locks down the retrieval baseline:

- valid and invalid LLM query parsing
- deterministic fallback parsing
- relation-family, direction, and `answer_mode` inference
- generic relationship-intent detection without forcing a relation family
- time-window filtering
- FTS punctuation behavior
- graph expansion for `REFERS_TO`, `DERIVED_FROM`, `SUPERSEDES`, and `RELATED`
- incoming `SUPERSEDES` traversal for relationship queries
- traversal through draft entities without surfacing them directly
- edge-weight pruning
- score formula and rank ordering
- relationship-first ranking and endpoint preservation
- access-count mutation without `updated_at` refresh
- end-to-end retrieval logging
- workspace-filtered retrieval
- fresh-database initialization before query
- regression corpus lookup quality

This file already proves that PAM is more than plain keyword search.

### `tests/test_relations.py`

This file is the dedicated relation regression suite.

It locks down relation behavior across both write and read paths:

- `REFERS_TO` formation through entity linking
- `DERIVED_FROM` formation through source provenance
- `RELATED` formation through shared entities and co-mentioned entities
- `DERIVED_FROM` formation through explicit ingest-time derivation cues against shared-entity neighbors
- `SUPERSEDES` formation through the feedback API and explicit ingest-time revision or replacement cues
- `CONTRADICTS` formation through explicit ingest-time negation cues when a nearby shared-entity note carries a positive recommendation
- explicit `CONTRADICTS` storage for conflict retrieval
- retrieval of each relation family through structured parsed queries
- graph-explanation rendering for influence, connection, evolution, theme, and gap prompts
- mixed relation context in a relation-dense corpus
- cross-discipline bridge retrieval across biology, music, transit, and planning notes
- multi-hop evolution coverage across successive `SUPERSEDES` edges

This suite matters because the repo now has enough relation-writing and relation-traversal behavior that a dedicated end-to-end regression file is justified rather than scattering these guarantees across unrelated modules.

### `tests/test_lifecycle.py`

This file locks down the maintenance baseline:

- decay math
- immunity of pinned nodes
- no-op decay for recent updates
- archiving threshold behavior
- unarchive behavior
- upvote, downvote, and pin semantics
- edge boosting on upvote
- supersede semantics and rejection cases

This matters because a personal-memory graph still needs dependable maintenance rules.

### `tests/test_cli.py`

This file protects the public control plane:

- `query_for_agent` delegation and workspace scoping
- `ingest_for_agent` routing and parent-note support
- agent context formatting sections and relationship rendering
- session UUID generation
- `add` argument routing into `ingest`
- `query --json` serialization
- `show` JSON output
- `graph` incoming and outgoing edge display

### `tests/test_detailed_agent_eval.py`, `tests/test_large_agent_eval.py`, and `tests/test_hard_agent_eval.py`

These three suites prove the current agent-facing retrieval story at increasing levels of difficulty.

The detailed suite proves:

- a checked-in 55-item corpus and 110 natural-language queries
- deterministic parser fallback under forced `LLMUnavailableError`
- post-ingest database health
- quality floors for direct, indirect, timeline, and relationship hits
- cross-discipline bridge queries over biology, music, transit, and planning analogies

The large suite proves:

- a 100-item corpus and 200 natural-language queries
- deterministic parser fallback under scale
- post-ingest database health
- lookup, paraphrase, relationship, timeline, and negative-query floors

The hard suite proves:

- a more ambiguous 96-item corpus and 192 queries
- alias-based prompts, overlapping rollout language, incident notes, residency links, and source provenance
- stricter scoring that checks expected relationship edges or source titles where applicable

Together these suites are the strongest maintained proof of current retrieval quality.

### `tests/test_copilot_cli_eval.py`

This file covers the evaluation harness itself:

- smoke tests for `scripts/run_copilot_cli_eval.py`
- lazy Copilot command discovery
- subprocess command construction and timeout handling
- scratch-directory lifecycle
- `main()` wiring for suite loading and miss output
- an opt-in live integration test against an isolated temporary PAM database

This matters because the live-boundary eval harness has failure modes that differ from the core PAM modules.

### Fixtures

- `tests/fixtures/retrieval_regression_corpus.json` validates direct lookup quality, paraphrase robustness, negative behavior, distractor handling, and top-hit stability for a curated subset of prompts
- `tests/fixtures/large_agent_eval_corpus.json` validates larger-scale mixed-content ingest plus direct, paraphrased, relationship, timeline, and negative-query behavior
- `tests/hard_agent_eval_fixture.py` generates the hard-suite scenario catalog and is maintained test source
- `.tmp_manual_cli/detailed_memory_eval/run_detailed_eval.py` is maintained because the detailed suite imports it directly

## What The Current Suite Does Not Yet Prove

For the intended graph-native personal-memory system, the biggest missing coverage areas are:

- influence-chain reasoning beyond explicit stored derivation or supersession
- multi-step idea evolution across more than one explicit edge
- theme centrality and conceptual clustering
- adjacent-topic or gap suggestions grounded in graph structure
- miss classification that distinguishes missing-edge, parse, expansion, ranking, and rendering failures
- richer ingest-time relation creation beyond entity mentions and source provenance

The current suite is strong for relation-aware retrieval. It is not yet a full graph-native reasoning suite.

## Recommended Next Evaluation Gates

The repo should add evaluation gates for the five question families that define the intended product.

### 1. Influence

Example target:

- what influenced my memory routing idea

Expected behavior:

- return the relevant prior sources, related notes, and implementation memories
- expose a believable explanation chain rather than only a bag of related hits

### 2. Connection

Example target:

- how are MCP and my memory work connected

Expected behavior:

- return the architectural relationship between the two workstreams
- distinguish direct stored links from inferred complementarity

### 3. Evolution

Example target:

- how has my thinking evolved over time

Expected behavior:

- recover an ordered chain of notes, sources, and corrections
- favor current views while still surfacing the historical chain

### 4. Themes

Example target:

- what are the central themes in my research

Expected behavior:

- identify connected concepts or clusters, not simply the most frequent words

### 5. Gaps

Example target:

- what important adjacent topics have I not explored

Expected behavior:

- propose nearby but underexplored topics and show the evidence frontier that made them plausible

## How To Read Coverage Today

The suite is already a meaningful contract for:

- storage correctness
- write correctness
- read correctness
- user-facing contract stability
- natural-language retrieval quality at detailed, large, and hard eval scales

But the acceptance story for the intended product is still incomplete until graph-native question classes are added as first-class automated gates.

One practical wrinkle remains: not all test data lives under `tests/`. The detailed evaluation suite intentionally imports its authored fixture from `.tmp_manual_cli/detailed_memory_eval/run_detailed_eval.py`, so that scratch tree currently mixes disposable outputs with one checked-in test dependency.

## Manual Copilot CLI Eval

The automated test suite keeps retrieval deterministic by forcing parser fallback and stubbing ingestion enrichment. For a live-boundary check, use `scripts/run_copilot_cli_eval.py`.

For an automated but opt-in live test, run `tests/test_copilot_cli_eval.py` with `PAM_RUN_REAL_COPILOT_TESTS=1`. The live test skips by default and also skips when the retrieval LLM provider is unavailable, because that case would only re-test deterministic fallback.

### What It Does

- loads one of the checked-in evaluation suites
- ingests that suite into an isolated database under `.tmp_manual_cli/copilot_cli_eval/<suite>/`
- retrieves PAM context locally through `pam.agent_interface.query_for_agent`
- asks GitHub Copilot CLI to answer from that retrieved context only, without MCP
- scores the returned answer against the suite expectations

### Requirements

- GitHub Copilot CLI installed and authenticated in the local environment
- Node.js available on `PATH`
- the PAM virtual environment at `.venv`
- for the live automated test, `PAM_RUN_REAL_COPILOT_TESTS=1`
- optional for the live automated test, `PAM_REAL_COPILOT_MODEL=<model-name>` to override the default model

### Example Commands

- `c:/workdir/PAM/.venv/Scripts/python.exe scripts/run_copilot_cli_eval.py --suite large --model claude-opus-4.6 --max-queries 10`
- `c:/workdir/PAM/.venv/Scripts/python.exe scripts/run_copilot_cli_eval.py --suite hard --model claude-opus-4.6 --max-queries 25 --include-misses`
- `$env:PAM_RUN_REAL_COPILOT_TESTS = "1"; c:/workdir/PAM/.venv/Scripts/python.exe -m unittest tests.test_copilot_cli_eval -q`

### Notes

- the harness sets `PAM_DB_PATH` and `PAM_LOG_PATH` to suite-specific temporary paths so it does not reuse the default repo database
- the current prompt strategy gives Copilot a bounded, content-rich PAM retrieval block rather than asking Copilot to drive CLI tools itself
- negative cases expect `NO_ANSWER`; the harness normalizes light formatting around that token before scoring
