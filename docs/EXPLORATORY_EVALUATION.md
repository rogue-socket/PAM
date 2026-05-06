# PAM Exploratory Evaluation

## Purpose

Document the maintained evaluation surfaces that sit above unit tests, record what those suites actually prove, and clarify what still needs to be evaluated for the intended graph-native personal-memory system.

## Maintained Evaluation Surfaces

### Retrieval Regression Corpus

`tests/test_retrieval.py` exercises the retrieval stack against a fixed regression corpus.

It covers:

- parser fallback behavior
- workspace-scoped FTS search
- time filtering on `valid_at`
- graph expansion across `REFERS_TO`, `DERIVED_FROM`, `SUPERSEDES`, and `RELATED`
- relationship-aware retrieval and ranking behavior

### Detailed Agent Evaluation Suite

`tests/test_detailed_agent_eval.py` runs a 55-item corpus and 110 natural-language queries through the agent interface.

The suite uses:

- `ingest_for_agent()` for corpus construction
- `query_for_agent()` for retrieval
- `check_database_health()` after ingest
- forced `LLMUnavailableError` for query parsing so the deterministic fallback path is exercised intentionally
- an authored cross-discipline bridge slice that stresses relation-aware retrieval across biology, music, transit, and planning analogies

Current enforced floor:

- direct hits: 32/32
- indirect hits: at least 58/78
- overall hits: at least 88/110
- timeline hits: at least 7
- relationship hits: at least 19

### Large Agent Evaluation Suite

`tests/test_large_agent_eval.py` runs a larger 100-item corpus and 200 natural-language queries through the same agent surface.

The suite asserts:

- healthy database state after ingest
- 100 ingested nodes
- no missing or orphaned FTS rows
- at least 92 percent overall score
- lookup floor: 76/80
- paraphrase floor: 36/40
- relationship floor: 34/40
- timeline floor: 16/20
- negative-query floor: 19/20

### Hard Agent Evaluation Suite

`tests/test_hard_agent_eval.py` pushes a more ambiguous corpus and tougher prompt mix through the same agent boundary.

It adds pressure on:

- alias-based prompts
- overlapping rollout language
- source provenance
- relationship edge correctness
- timeline behavior under distractors

## Evaluation Harness Characteristics

Across the maintained agent-level suites:

- ingest and retrieval are evaluated through `pam.agent_interface`, not by directly poking low-level DB helpers
- LLM-assisted ingest enrichment is mocked away, so the suites primarily validate deterministic extraction, linking, graph structure, and retrieval behavior
- query parsing is forced into deterministic fallback mode, so offline behavior is a tested baseline rather than an aspirational claim
- store health is checked programmatically through `check_database_health()`, not through a CLI operator command

## What The Current Evaluation Story Proves

The current automated and exploratory evidence supports these conclusions.

### Working reliably today

- fresh database bootstrap is exercised by both CLI setup and library entrypoints
- deterministic offline retrieval is a real supported path
- relationship-aware retrieval is a first-class evaluation target rather than an ad hoc observation
- explicit revision tracking through `SUPERSEDES` is one of the stronger product surfaces
- FTS parity is explicitly checked in the detailed and large agent suites
- cross-discipline bridge prompts now exist in the maintained detailed eval, so the evaluation story is no longer limited to one domain at a time

### Product friction still visible today

- default human `query` output is still flatter than the JSON and agent surfaces
- broad topical queries are still sensitive to lexical overlap and can let large source documents outrank concise answer-bearing notes
- natural language phrased as influence, themes, or "what changed" is weaker than explicit relation wording such as `replaced` or `superseded`
- the current evaluation floors say more about retrieval quality than about graph-native reasoning quality

## What The Current Evaluation Story Does Not Prove

This is the key stale-doc fix.

The current suite does not yet prove that PAM can reliably answer graph-native personal-memory questions such as:

- what influenced this idea
- how two workstreams connect architecturally
- how a line of thinking evolved across several memories
- what the central themes are in a corpus
- what nearby but underexplored topics exist

Those question classes require stronger evaluation around paths, clusters, and graph diagnostics, not only ranked nodes and explicit edges.

The newer bridge prompts move the maintained evaluation closer to that goal, but they still measure relation-aware retrieval more than full graph-native reasoning.

## Historical Manual Findings

Historical manual persona runs under `.tmp_manual_cli/` remain useful as exploratory evidence, but not as the authoritative oracle.

The consistent pattern across those runs was:

- direct recall is often good enough already
- explicit supersession questions are stronger than general change-oriented phrasing
- note-versus-source balancing can still be poor on broad queries
- the agent-facing formatter usually exposes graph context better than the plain human CLI formatter

When those manual artifacts disagree with maintained tests or current code, the code and maintained tests win.

## Evaluation Artifacts Under `.tmp_manual_cli/`

### Maintained input artifact

`.tmp_manual_cli/detailed_memory_eval/run_detailed_eval.py` is a maintained support script because `tests/test_detailed_agent_eval.py` imports its corpus, queries, and supersession fixtures.

### Generated historical artifacts when present

Generated outputs under `.tmp_manual_cli/detailed_memory_eval/` can include dataset snapshots, result JSON, summary markdown, and a local `run/` workspace when the detailed workflow is executed manually.

These artifacts are useful as historical snapshots, but they can drift from the current CLI and schema and are not required to be checked in. When they disagree with the code or maintained tests, the code and tests win.

## Recommended Next Evaluation Layer

To support the intended graph-native architecture, PAM should add first-class evaluation coverage for five question families.

### 1. Influence

Representative query:

- what influenced my memory routing idea

Expected result shape:

- a set of source and note memories plus an explanation chain

### 2. Connection

Representative query:

- how are MCP and my memory work connected

Expected result shape:

- explicit architectural complementarity or relation evidence, not only co-matching notes

### 3. Evolution

Representative query:

- how has my thinking evolved over time

Expected result shape:

- an ordered chain of memories with replacement, derivation, or related transitions

### 4. Themes

Representative query:

- what are the central themes in my research

Expected result shape:

- central connected concepts or clusters, not merely frequent tokens

### 5. Gaps

Representative query:

- what important adjacent topics have I not explored

Expected result shape:

- nearby but underexplored topics backed by a visible evidence frontier

## Recommended Diagnostics

For graph-native evaluation, aggregate hit rates are not enough. Misses should be bucketed into at least these classes:

- parser miss
- anchor-resolution miss
- missing-edge miss
- expansion miss
- ranking miss
- rendering or explanation miss

That classification is what will let the repo improve the right subsystem instead of just tweaking weights globally.

## Bottom Line

PAM's maintained evaluation story is already meaningful: deterministic retrieval, explicit relation handling, and revision tracking are all real. But the evaluation story is still narrower than the intended product. The next evaluation layer needs to test graph-native reasoning directly, not infer it from improved lookup scores.