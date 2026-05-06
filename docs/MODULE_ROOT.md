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
- `MAX_GRAPH_DEPTH`
- `ENTITY_BOOST_SCORE`
- `EDGE_WEIGHT_EXPANSION_THRESHOLD`

#### Ranking weights

- `WEIGHT_TEXT_RELEVANCE`
- `WEIGHT_RECENCY`
- `WEIGHT_IMPORTANCE`

These are still intended to sum to `1.0` before the separate entity bonus is applied.

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
