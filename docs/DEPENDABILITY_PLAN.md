# PAM Dependability Plan

## Goal

Describe PAM's current dependability posture accurately, separate what is already implemented from what is still missing, and focus future work on the gaps that materially affect correctness, recoverability, operator trust, and graph truthfulness.

## Dependability Bar

For the intended personal-memory system, PAM is dependable when all of the following are true:

- fresh databases work through both CLI and library entrypoints without manual bootstrap
- multi-step mutations are atomic or have a clear, bounded compensation story
- retrieval semantics across `active`, `draft`, `reference`, and `archived` nodes are intentional and documented
- missing or malformed LLM behavior never breaks supported ingest or retrieval flows
- operators can inspect store health and repair derived state without ad hoc SQLite surgery
- graph-native answers are grounded in stored evidence rather than opaque model guesses
- relation and path failures can be diagnosed instead of appearing as generic bad retrieval
- documentation and generated artifacts do not overstate surfaces that the code does not actually expose

## Current Snapshot

### Implemented Today

#### 1. Self-Bootstrapping Entry Points

Implemented.

Evidence in code:

- `cli.py` initializes schema on every command-group invocation
- `pam.retrieval.search.retrieve()` uses `get_initialized_connection()`
- `pam.ingestion.pipeline.ingest()` initializes the connection it uses

Practical effect:

- there is no hidden requirement to run `migrate` before normal use

#### 2. Offline Deterministic Fallback Contract

Implemented.

Evidence in code:

- query parsing falls back to deterministic parsing when the provider is missing or the LLM response is malformed
- deterministic parsing covers keywords, simple date ranges, relation families, relation direction, and relationship-first answer mode
- ingest-time LLM helpers degrade to empty summary, entity, or edge-fact outputs

Practical effect:

- missing SDKs do not block ingestion or retrieval

#### 3. Dependable Provenance And Revision Baseline

Implemented, but limited in scope.

Evidence in code:

- `DERIVED_FROM` creation is dependable for source-parent flows, including dedup hits
- `SUPERSEDES` creates explicit replacement edges and marks older nodes as `reference`
- retrieval already knows how to surface both provenance and supersession context

Practical effect:

- PAM already preserves some of the user's changing thinking explicitly rather than only through ranking heuristics

#### 4. Draft-Entity Retrieval Semantics

Implemented.

Evidence in code:

- entity linker creates new entities as `draft`
- graph expansion treats draft entities as traversable bridge nodes
- draft entities are not surfaceable top-level results
- `reference` nodes can still surface for supersession context

Practical effect:

- recall can improve through entities without cluttering top-level results with auto-created drafts

#### 5. Store Health Checks — Programmatic And Operator-Facing

Implemented.

Evidence in code:

- `check_database_health()` reports node count plus missing and orphaned FTS rows
- `doctor_report()` adds schema version, `PRAGMA integrity_check`, vector-channel coverage, and missing-embedding counts
- the `pam doctor` CLI command surfaces all of this and exits non-zero on drift; `pam rebuild-fts` rebuilds the FTS index
- detailed and large agent evaluation suites assert healthy FTS state after corpus ingest

Practical effect:

- FTS and integrity drift can be detected and repaired through a first-class CLI surface, not only in code and tests

#### 6. Evaluation Coverage For Relation-Aware Retrieval

Implemented.

Maintained checks include:

- unit coverage for parser fallback, graph expansion, ranking, ingest, lifecycle, and CLI behavior
- retrieval regression corpus tests in `tests/test_retrieval.py`
- detailed, large, and hard agent evaluation floors

Practical effect:

- the repo has a meaningful dependability story for deterministic retrieval and explicit relation handling

## Gap Ledger

Gaps are tracked here whether open or resolved; resolved entries keep the history of what shipped.

### 1. Transactional Write Boundaries

Resolved (2026-05-19).

Evidence in code:

- `pam/db/transaction.py` provides a `transaction()` context manager (`BEGIN`/`COMMIT`, `SAVEPOINT` when nested)
- low-level node and edge mutators accept a `commit` keyword so they can defer their commit inside a `transaction()` block
- `ingest()`, `link_entities_detailed()`, `apply_supersedes()`, `apply_decay()`, and `upvote()` run their multi-write work inside a `transaction()` block
- failure-injection tests (`tests/test_ingestion_atomicity.py`, `tests/test_orchestrator_atomicity.py`, `tests/test_transaction.py`) assert rollback

Practical effect:

- multi-step writes are atomic; the old delete-the-main-node compensation path is gone

### 2. Telemetry Is Best-Effort, Not Atomic

Partially implemented by design.

Current limitation:

- JSONL telemetry is appended outside SQLite transactions
- logs are useful for debugging, but they are not an audit log and can diverge from partially failed operations

Why it matters:

- operators should not infer correctness from the presence or absence of a log line alone

Required documentation stance:

- keep describing `pam_log.jsonl` as telemetry only

### 3. Operator-Facing Health Tooling

Resolved (2026-05-19).

Evidence in code:

- `pam doctor` reports schema version, `PRAGMA integrity_check`, FTS drift, vector-channel coverage, and missing-embedding counts, and exits non-zero on drift
- `pam rebuild-fts` wipes and rebuilds `fts_index` from `nodes` inside one transaction

Practical effect:

- routine inspection and FTS repair no longer require Python code or direct SQLite access

### 4. Graph Truthfulness Diagnostics Are Still Thin

Partially implemented.

Current state:

- the eval harness has a coarse 5-class miss classifier (`subprocess_error` / `false_positive` / `retrieval_miss` / `partial_surface` / `pick_miss`) in `scripts/run_copilot_cli_eval.py`
- it does not yet distinguish missing-edge vs missed-expansion vs weak-ranking vs weak-rendering — those still collapse into one class because the classifier only sees the final rendered context

Why it matters:

- as PAM becomes more graph-native, wrong relational answers are higher-risk than ordinary lexical misses

Recommended next step:

- add per-stage miss categorization (retrieval vs expansion vs ranking vs rendering) once `retrieval_miss` proves the dominant class — see `backlog.md`

### 5. Schema Provenance Is Only Partly Versioned

Partially implemented.

Current limitation:

- `schema_version` only records versioned migrations
- `_ensure_schema_compatibility()` performs workspace-id repair outside the migration ledger

Why it matters:

- `schema_version` alone is not a complete provenance record for an upgraded store

Recommended next step:

- convert compatibility repairs into explicit versioned migrations once the schema needs another formal revision

### 6. Human Operator Feedback Is Still Thin

Not a correctness failure, but still a dependability concern.

Current examples:

- `add` prints `Added:` even when ingest returned an existing deduped node id
- `show` does not surface supersession or provenance context directly
- graph-native question classes still depend on richer JSON or agent formatting more than the plain human surface

Why it matters:

- correct behavior is harder to verify from the default human interface than from JSON output or direct graph inspection

### 7. Legacy Manual Evaluation Outputs Can Drift

Current limitation:

- generated outputs under `.tmp_manual_cli/detailed_memory_eval/` can include result JSON or summary markdown when someone runs the manual workflow locally
- those outputs can reflect older CLI or schema assumptions and are not part of the maintained test oracle

Why it matters:

- readers can confuse historical manual outputs with the current supported surface or with graph-native guarantees the code does not yet make

Required documentation stance:

- treat maintained tests as authoritative and generated manual summaries as illustrative only

## Prioritized Next Work

### Phase 1 — done (2026-05-19)

- transaction boundaries for ingest, feedback, lifecycle, and unarchive — shipped
- failure-injection coverage for rollback behavior — shipped

Outcome:

- PAM stopped relying on compensating cleanup and gained a real atomic write story.

### Phase 2 — done (2026-05-19), one item carried forward

- store health checks exposed through `pam doctor` — shipped
- FTS rebuild support (`pam rebuild-fts`) — shipped
- graph-quality diagnostics and miss categorization — partially shipped (coarse 5-class classifier); per-stage categorization carried forward, see Gap 4

Outcome:

- operators can inspect and repair search-state issues without writing Python or SQL by hand; finer graph-quality diagnostics remain open.

### Phase 3

- move compatibility repairs into versioned migrations
- tighten human CLI feedback around dedupe, provenance, and replacement context
- keep generated manual evaluation outputs clearly labeled as non-authoritative

Outcome:

- the system's stored history, health signals, and documentation all tell the same story.

## Exit Criteria For The Next Dependability Milestone

- fresh-database behavior remains bootstrap-safe through CLI and library APIs
- ingest, feedback, lifecycle, and unarchive are atomic under injected failures
- health and repair tooling are available through a stable operator CLI
- graph-native misses can be diagnosed by failure class
- schema provenance is fully versioned
- docs and generated evaluation artifacts no longer imply unsupported guarantees

## Explicit Non-Goals

- remote sync or multi-user coordination
- replacing SQLite
- claiming graph-native reasoning guarantees that the stored evidence cannot support
- using vector search or embedding storage as a substitute for a dependable memory graph