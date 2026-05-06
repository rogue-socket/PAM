# PAM Architecture

## Purpose

PAM should be a local-first personal agent memory system, not just a note store with search. The memory graph is the primary model of the user's work. Search, optional LLM help, and any future vector or embedding layer are supporting mechanisms for building and traversing that graph.

The product question this architecture needs to answer is:

How does a personal agent recover not only the right note, but also the relationships that explain why that note matters now?

## Documentation Stance

This document distinguishes between two things:

- Current baseline: what the repository implements today.
- Intended implementation: what PAM should implement for the personal-memory use case.

The current code is already relation-aware. It is not yet graph-native in the stronger sense needed for influence chains, idea evolution, thematic clustering, and adjacent-topic discovery.

## Product Thesis

The personal-memory use case requires PAM to answer questions like these reliably:

- What influenced my memory routing idea?
- How are MCP and my memory work connected?
- How has my thinking evolved over time?
- What are the central themes in my research?
- What important adjacent topics have I not explored?

Those questions are not primarily lexical. They depend on:

- typed relationships between memories
- provenance from notes back to sources
- temporal ordering and supersession
- paths across multiple related memories
- graph structure strong enough to expose themes and gaps

## Current Baseline

### What Exists Today

PAM currently provides:

- local SQLite-backed storage with first-class nodes and edges
- workspace scoping through `workspace_id`
- FTS5 lookup over title, content, and summary
- optional LLM help for summarization, entity extraction, edge facts, and query parsing
- deterministic offline fallback for both ingest and query parsing
- relation-aware query parsing, graph expansion, and edge ranking for explicit relation families
- stable CLI and agent-facing retrieval boundaries

This is a real baseline. The docs should not pretend the repo is still pure keyword search.

### What Is Still Missing

For the personal-memory use case, the current baseline is still missing several critical properties:

- ingest writes too little high-value graph structure beyond entity references, source provenance, and narrow cue-based derivation, supersession, or contradiction
- retrieval remains FTS-led, so graph reasoning usually starts only after lexical candidates are found
- explicit relation queries are stronger than generic graph questions such as influence, themes, evolution, or adjacent topics
- result payloads expose relationships, but not richer explanation paths, cluster summaries, or missing-edge diagnostics
- the evaluation suites mostly prove retrieval quality and explicit relation handling, not graph-native reasoning quality

## Design Goals

- Keep all durable state local, inspectable, and workspace-scoped.
- Preserve a deterministic minimum contract when models are unavailable.
- Treat graph structure as the memory model, not decorative metadata.
- Represent thought evolution explicitly enough to answer change-over-time questions.
- Expose answers that are explainable through nodes, edges, timestamps, and provenance.
- Keep the CLI and agent interface stable while the internals become more graph-native.
- Favor dependable write-time relation creation over speculative reasoning with weak support.

## Top-Level Component Map

- Root files
  - `cli.py`: human CLI.
  - `config.py`: tuning knobs and runtime defaults.
- `pam/`
  - `db/`: schema setup, storage helpers, FTS, and health checks.
  - `ingestion/`: normalization, extraction, optional model enrichment, and graph construction.
  - `retrieval/`: query parsing, anchor resolution, candidate selection, graph traversal, and ranking.
  - `lifecycle.py`: decay, archive, and unarchive behavior.
  - `feedback.py`: upvote, downvote, pin, and supersede mutations.
  - `agent_interface.py`: agent-facing ingest, retrieval, and context formatting.
  - `chat_agent.py`: grounded answer generation on top of PAM retrieval.
- `tests/`
  - unit coverage
  - retrieval regression corpus
  - detailed, large, and hard agent evaluation suites
- `.tmp_manual_cli/`
  - scratch evaluation state
  - one maintained detailed-eval fixture script at `detailed_memory_eval/run_detailed_eval.py`

## Runtime Model

### Entry-Point Initialization

Public entrypoints initialize schema before doing useful work:

- `cli.py` opens a connection with `get_connection()` and immediately calls `initialize()`
- `pam.retrieval.search.retrieve()` uses `get_initialized_connection()`
- `pam.ingestion.pipeline.ingest()` initializes either its owned connection or the caller-provided one

Fresh-database bootstrap is part of the normal runtime contract, not a separate operator step.

### Database

Authoritative state lives in `pam.db`.

Key schema elements today:

- `nodes`: primary memory records
- `edges`: graph relationships between nodes
- `fts_index`: FTS5 virtual table over title, content, and summary
- `schema_version`: applied versioned migrations

Connection defaults:

- WAL mode enabled
- foreign keys enabled
- busy timeout enabled
- rows exposed as `sqlite3.Row` values

Compatibility note:

- versioned migrations currently stop at schema version 1
- older stores missing `workspace_id` are repaired by `_ensure_schema_compatibility()` during initialization

### Health Checks

The current health API is programmatic, not CLI-driven.

`pam.db.schema.check_database_health()` verifies:

- total node count
- missing FTS rows for existing nodes
- orphaned FTS rows with no corresponding node

That is necessary, but not sufficient, for a graph-native memory system. Over time PAM also needs diagnostics that distinguish:

- missing edge creation
- missed anchor resolution
- missed graph expansion
- wrong edge ranking
- good nodes but weak explanation assembly

### Telemetry

Best-effort JSONL telemetry is written to `pam_log.jsonl`.

Observed event classes include:

- `ingest`
- `query`
- `decay`
- `archive`
- `upvote`
- `downvote`
- `pin`
- `supersede`

Telemetry is helpful for inspection, but SQLite remains authoritative. Logging is append-only and not transactional with database commits.

### Workspace Scope

Every node carries a first-class `workspace_id`.

That scope is used to:

- keep dedupe local to one workspace
- keep retrieval from mixing unrelated projects
- keep entity linking local to the active workspace

The canonical identifier is the resolved absolute path of the current working directory or an explicit caller override.

## Data Model

### Node Types

- `event`: task-like or time-bounded memory, usually from `task` input
- `note`: durable belief, idea, or observation
- `entity`: person, tool, project, concept, organization, place, or other linked object
- `source`: file, URL, or document-backed reference

### Node Fields

- `id`: UUID string
- `type`: one of `event`, `entity`, `note`, `source`
- `title`: short label
- `content`: full text body
- `summary`: optional model-generated summary
- `content_hash`: normalized dedupe hash within workspace scope
- `created_at`: write time
- `valid_at`: event or source time used by retrieval recency filters
- `updated_at`: mutation time used by decay
- `tags`: JSON-encoded labels
- `session_id`: optional grouping token
- `importance`: ranking and lifecycle weight
- `access_count`: retrieval counter
- `status`: `active`, `draft`, `reference`, or `archived`
- `metadata`: node-type-specific JSON payload
- `workspace_id`: owning workspace scope

### Edge Relations

Current stored relation families are:

- `REFERS_TO`: note or event to entity
- `DERIVED_FROM`: note to source provenance edge
- `RELATED`: general relationship edge used for reasoning-style expansion
- `CONTRADICTS`: conflict edge surfaced in results
- `SUPERSEDES`: replacement edge from newer note or entity to older note or entity

For the intended implementation, this edge set should be treated as a dependable minimum, not necessarily a final ontology. The important requirement is that PAM can represent:

- provenance
- supersession and correction
- conceptual relatedness
- contradiction
- influence and reuse
- architectural complementarity
- temporal evolution

If that requires richer edge typing or edge metadata later, the implementation should add it only when write-time rules are dependable enough to maintain graph quality.

## Query And Result Contracts

### Parsed Query Shape Today

`pam.retrieval.query_parser.ParsedQuery` carries:

- `keywords`
- `entities`
- `time_range`
- `intent`
- `relation_filters`
- `relation_direction`
- `answer_mode`
- `anchor_terms`

The parser may use an LLM, but deterministic fallback also infers simple date ranges, relation families, relation direction, and relationship-oriented answer mode.

### Query Planning Needed Next

For the personal-memory use case, query understanding needs to recognize answer shapes beyond direct lookup:

- direct fact lookup
- explicit relationship lookup
- influence and provenance tracing
- temporal evolution
- thematic synthesis
- adjacent-topic or gap discovery

PAM does not need to solve all of that through opaque model calls. It does need an explicit query plan that tells retrieval which graph behavior is being requested.

### Retrieval Result Shape Today

`pam.retrieval.ranker.RetrievalResult` exposes:

- node buckets: `events`, `entities`, `notes`, `sources`
- `relationships`
- compatibility views: `conflicts` and `superseded`
- `edge_facts`
- `session_groups`
- `query_meta`
- `ordered_nodes`

This is a good machine-facing baseline. It is not yet rich enough to explain why an influence path won, why a theme was judged central, or why a gap suggestion was proposed.

### Result Contract Needed Next

The intended implementation should eventually support richer explanation payloads such as:

- winning paths or relationship chains
- explanation labels for why a node or edge was selected
- cluster or theme summaries grounded in graph structure
- gap suggestions with the evidence frontier that made them plausible
- failure diagnostics when a graph-style query fell back to lexical behavior

## Subsystem Responsibilities

### DB Layer

Responsible for:

- connection setup and initialization
- versioned migrations and compatibility repair
- node and edge CRUD
- FTS lookup and FTS health inspection
- workspace and timestamp normalization helpers

Not responsible for:

- query intent inference
- ingest business rules
- lifecycle policy

### Ingestion Layer

Responsible today for:

- validating input kinds
- deterministic extraction of title, content, metadata, and content hash
- URL fetch and source-type heuristics
- workspace-scoped dedupe
- optional summary and entity extraction
- entity linking and draft entity creation
- note-to-source provenance edges
- ingest telemetry

Responsible next for:

- constructing a graph that preserves idea evolution and conceptual relationships, not only entity mentions
- writing dependable cross-memory links when the evidence supports them
- keeping provenance for inferred links explicit enough that retrieval can explain them later

### Retrieval Layer

Responsible today for:

- parsing raw queries
- candidate FTS search with workspace and time filtering
- graph expansion over supported relations
- ranking nodes or relationships
- incrementing `access_count`
- query telemetry

Responsible next for:

- graph-first or graph-equal query planning when the question is relational, temporal, thematic, or gap-oriented
- constrained multi-hop reasoning over the stored memory graph
- explanation assembly that surfaces why the answer was selected

### Lifecycle And Feedback Layer

Responsible today for:

- decay based on `updated_at`
- archiving below threshold
- unarchive restoration
- explicit feedback mutations
- supersession behavior for notes and entities

Responsible next for:

- preserving the user's evolving thinking without collapsing old context too aggressively
- making replacement, contradiction, and long-term relevance visible enough that retrieval can prefer the current thought while still explaining the older chain

### CLI And Agent Surface

Human CLI currently exposes:

- `add`
- `session start`
- `query`
- `chat`
- `upvote`, `downvote`, `pin`
- `supersede`
- `decay`
- `unarchive`
- `show`
- `list`
- `graph`
- `migrate`
- `stats`

Agent-facing helpers currently expose:

- `ingest_for_agent()`
- `query_for_agent()`
- `format_for_context_window()`

The intended implementation should keep these boundaries stable while making graph explanations visible through them.

## Core Invariants

- Public entrypoints initialize schema before use.
- Main nodes are created before dependent edges.
- Foreign keys remain enabled, so missing edge endpoints still fail hard.
- FTS stays synchronized through triggers rather than manual dual writes.
- Retrieval increments `access_count` but does not refresh `updated_at`.
- Decay uses `updated_at`; time filtering and recency scoring use `valid_at`.
- Dedupe is scoped by `workspace_id` and ignores archived nodes.
- Draft entities are traversable graph bridges but not directly surfaceable results.
- Reference nodes are surfaceable for supersession context.
- URL and file provenance from a note to a source is modeled with `DERIVED_FROM`.
- Current relationship queries only become relationship-first when `answer_mode` is `relationship` and `relation_filters` is non-empty.
- Intended graph-native reasoning must stay explainable in terms of stored nodes, stored edges, timestamps, and provenance rather than hidden model guesses.

## Ranking Model

### Current Ranking

Node ranking combines:

- transformed BM25 text relevance
- recency from `valid_at`
- explicit `importance`
- optional entity-match bonus

Relationship ranking combines:

- edge weight
- source and target node scores
- a small bonus for stored edge facts
- a direction-match bonus when the query asked for incoming or outgoing relationships

### Required Shift

This ranking model is still fundamentally node-centric. For the personal-memory use case, PAM needs to add graph-native scoring for:

- path quality, not only node quality
- relation specificity and provenance strength
- temporal continuity across an idea chain
- theme centrality across multiple connected memories
- novelty and adjacency when proposing unexplored topics

That does not mean abandoning lexical signals. It means lexical signals should stop being the main reason a graph question succeeds.

## Failure And Fallback Behavior

- Missing LLM SDKs do not block ingest or query parsing.
- Missing ingest-time LLM helpers silently degrade to empty summaries, entities, or edge facts.
- Invalid LLM query JSON degrades to deterministic parsing with a warning.
- Missing LLM query providers degrade to deterministic parsing without a warning.
- Deterministic fallback recognizes explicit ISO dates, `today`, `yesterday`, `this week`, `last week`, `since DATE`, `after DATE`, `before DATE`, and simple relationship language.
- URL fetch failures degrade to hostname-plus-URL fallback for sources.
- Duplicate edges are treated as safe no-op writes.

The deterministic floor is a hard requirement for this architecture. The graph-native implementation can use models to enrich relation supply and query planning, but it cannot depend on them exclusively.

## Operational Boundary

PAM is a local component. Remote models are optional helpers, not a required control plane. Ingest and retrieval continue to function through deterministic paths when model access is unavailable.

## Recommended Implementation Order

1. Improve ingest-time graph construction so the graph contains more than entity mentions and provenance.
2. Extend query planning so influence, evolution, theme, and adjacent-topic questions take an explicit graph path.
3. Make candidate selection less dependent on lexical FTS when graph intent is clear.
4. Add explanation payloads and failure diagnostics to the retrieval result contract.
5. Add evaluation gates that measure graph-native reasoning instead of only relation-aware retrieval.
