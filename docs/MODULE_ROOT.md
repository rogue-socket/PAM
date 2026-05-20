# Root And Package Modules

## `config.py`

### Purpose

`config.py` remains the single constants module for PAM. It does not load config dynamically and it does not hold runtime state.

For the updated documentation stance, one point matters: the current constant set still reflects an FTS-led, relation-aware retriever. As PAM becomes more graph-native, new tuning knobs will likely appear here for query planning, path scoring, explanation budgets, and graph diagnostics.

### Current Constant Groups

#### Paths

- `DB_PATH`
- `LOG_PATH`

#### Retrieval

- `TOP_K`
- `FTS_CANDIDATE_LIMIT`
- `VEC_CANDIDATE_LIMIT`
- `VEC_SIMILARITY_FLOOR`
- `ENTITY_BOOST_SCORE`
- `EDGE_WEIGHT_EXPANSION_THRESHOLD`
- `RELATIONSHIP_PRIORITY_BONUS`
- `DERIVED_PROPAGATION_ALPHA`
- `DERIVED_PROPAGATION_SEED_FLOOR`
- `DERIVED_PROPAGATION_SINK_CEILING`

#### Ranking weights

- `WEIGHT_TEXT_RELEVANCE`
- `WEIGHT_VEC_SIMILARITY`
- `WEIGHT_RECENCY`
- `WEIGHT_IMPORTANCE`

These four weights currently sum to `1.10` (the hybrid-retrieval split added `WEIGHT_VEC_SIMILARITY`); the entity bonus is applied additively on top. The contract is "score components sum to the rank-key," not "weights sum to 1.0."

#### Lifecycle

- `DECAY_LAMBDA`
- `ARCHIVE_THRESHOLD`

#### Entity extraction and linking

- `MAX_ENTITIES_PER_INGESTION`
- `ENTITY_CATEGORIES`
- `ENTITY_FUZZY_MATCH_THRESHOLD`
- `ENTITY_FUZZY_MATCH_THRESHOLD_FTS`

#### Session and feedback

- `SESSION_STALENESS_HOURS`
- `UPVOTE_DELTA`
- `DOWNVOTE_DELTA`
- `EDGE_UPVOTE_DELTA`
- `SUPERSEDE_IMPORTANCE_FACTOR`
- `IMPORTANCE_MAX`
- `IMPORTANCE_MIN`
- `IMPORTANCE_DEFAULT`

#### LLM

- `LLM_PROVIDER`
- `LLM_TIMEOUT_SECONDS`
- `LLM_INGESTION_MODEL` — Anthropic model for ingest summary/entity extraction (default `claude-haiku-4-5`, env override `ANTHROPIC_MODEL`).
- `LLM_QUERY_PARSER_MODEL` — Anthropic model for query parsing (default `claude-sonnet-4-5`, env override `ANTHROPIC_MODEL`).
- `LLM_INGESTION_OPENAI_MODEL` — OpenAI model for ingest enrichment when `LLM_PROVIDER=openai` (default `gpt-4o-mini`, env override `OPENAI_MODEL`).
- `LLM_QUERY_PARSER_OPENAI_MODEL` — OpenAI model for query parsing when `LLM_PROVIDER=openai` (default `gpt-4.1-mini`, env override `OPENAI_MODEL`).
- `LLM_CLAUDE_CODE_MODEL` — model passed to the Claude Code CLI when `LLM_PROVIDER=claude_code` (default `claude-haiku-4-5`, env override `CLAUDE_CODE_MODEL`).
- `CHAT_ANSWER_MODEL` — Copilot model for `chat_agent.answer_with_pam` (default `claude-sonnet-4.5`, env override `PAM_CHAT_ANSWER_MODEL`). Re-exported as `pam.chat_agent.DEFAULT_CHAT_MODEL`.

### What Config Is Still Missing For The Intended System

If PAM moves toward graph-native retrieval, `config.py` will probably need space for settings such as:

- graph-versus-lexical retrieval policy thresholds
- maximum explanation-path depth
- centrality or theme-scoring weights
- adjacency or gap-suggestion thresholds
- graph-diagnostic verbosity

Those settings do not need to be added prematurely, but the docs should make clear that the current config surface is tuned for the current baseline, not the full intended architecture.

### How Other Modules Use It

- DB uses path defaults
- ingestion uses entity thresholds, session staleness, importance defaults, and LLM settings
- retrieval uses search limits, expansion thresholds, ranking weights, and LLM settings
- lifecycle and feedback use importance bounds and delta values

## `pam/__init__.py`

### Purpose

The package root is deliberately minimal.

### Current Export Contract

`pam/__init__.py` currently exports only:

- `db`
- `ingestion`

It does not re-export selected functions, dataclasses, or the broader package tree.

### Practical Entry Points

The meaningful top-level entry points are:

- `cli.py` for human interaction
- `pam.agent_interface` for agent integration and stable context delivery
- `pam.ingestion.pipeline.ingest` for write orchestration
- `pam.retrieval.search.retrieve` for read orchestration
- `pam.lifecycle` and `pam.feedback` for maintenance operations

The intended graph-native direction does not require a broader package root. The stable entrypoints should remain the same while deeper modules grow richer behavior.

## `pam/embeddings.py`

### Purpose

Embedding helper for hybrid retrieval. Lazy-loads the `BAAI/bge-small-en-v1.5` sentence-transformer (384-dim) on first use and returns vectors as little-endian float32 bytes for the sqlite-vec `vec_nodes` table.

### Public surface

- `embed_text(text)` / `embed_query(text)` — embed a passage / a query (the query form applies BGE's retrieval prefix); both return `None` when the model is unavailable
- `embed_and_store_node(conn, node_id, text, *, commit=True)` — embed and write into `vec_nodes` + `vec_node_map`; returns `False` (no exception) when embeddings or the vec table are unavailable
- `backfill_embeddings(conn)` — embed every node with no `vec_node_map` row; idempotent, and raises `EmbeddingsUnavailable` because an explicit operator command should fail loudly rather than tier down silently
- `is_available()`, `EMBEDDING_DIM`, `MODEL_ID`, `BackfillStats`, `EmbeddingsUnavailable`

### Deterministic-fallback contract

If the model or `sentence-transformers` / `torch` is missing — or `PAM_DISABLE_EMBEDDINGS` is set — the embed functions return `None` and retrieval degrades to FTS-only. Only `backfill_embeddings()` raises, because it is an explicit operator action.

## `pam/telemetry.py`

### Purpose

Single best-effort log-append helper shared by ingestion, retrieval, lifecycle, and feedback.

### Public surface

- `append_log_line(log_path, payload)` — append one JSON line, flushed and `fsync`'d

### Contract

Telemetry is best-effort and **not** transactional with SQLite commits: `append_log_line()` swallows `OSError` (disk full, permissions) so telemetry can never block or fail a successful PAM operation. The caller owns the payload structure; the helper adds no timestamps.

## Cross-Cutting Note: Workspace Scoping

Workspace partitioning is a first-class part of the system behavior.

- `workspace_id` is resolved in `pam.db.schema.resolve_workspace_id()`
- ingestion carries the resolved workspace through normalization and dedup
- retrieval scopes FTS and ranking to the resolved workspace when provided

For a personal-memory system, this matters because graph reasoning is only trustworthy if the graph itself is scoped correctly. Cross-workspace contamination would corrupt both retrieval and the higher-order reasoning built on top of it.

## What Does Not Belong Here

- SQL schema details
- ingestion ordering rules
- retrieval ranking logic
- CLI routing details
- test-only helpers
