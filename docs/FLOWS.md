# PAM Flows

This document now does two things:

- describe the live end-to-end behavior accurately
- show the flow changes required for PAM to behave like a graph-native personal memory system

## Query Flow

### Current Baseline

This is the live retrieval path used by both the CLI and the agent interface.

1. A caller invokes `cli.py query ...`, `pam.agent_interface.query_for_agent(...)`, or `pam.retrieval.search.retrieve(...)` directly.
2. `pam.retrieval.search.retrieve()` opens a schema-initialized connection with `get_initialized_connection()`.
3. `pam.retrieval.query_parser.parse_query_with_metadata()` converts raw text into a `ParsedQuery` with:
   - `keywords`
   - `entities`
   - `time_range`
   - `time_range_relative`
   - `intent`
   - `relation_filters`
   - `relation_direction`
   - `answer_mode`
   - `question_shape`
   - `anchor_terms`
4. If LLM parsing is unavailable or fails, the parser falls back to deterministic parsing.
5. Deterministic fallback can infer:
   - simple keyword sets
   - timeline intent from explicit ISO dates and phrases such as `today`, `yesterday`, `this week`, and `last week`
   - range operators such as `since DATE`, `after DATE`, and `before DATE`
   - relation families such as `SUPERSEDES`, `DERIVED_FROM`, `REFERS_TO`, `CONTRADICTS`, and `RELATED`
   - incoming or outgoing relationship direction
   - relationship-oriented answer mode, including generic relation intent that does not always infer a concrete relation family
6. `pam.retrieval.search.fts_search_with_filter()` turns parsed keywords into an FTS lookup, and `pam.retrieval.search.vector_search()` embeds the raw query and retrieves the nearest `vec_nodes` rows by cosine similarity (vector search returns nothing when embeddings are unavailable, so retrieval degrades cleanly to FTS-only).
7. `pam.db.fts.fts_search()` filters candidates by:
   - `status = active`
   - resolved `workspace_id`
   - optional `valid_at` bounds
8. `fts_search_with_filter()` applies an overlap-based precision filter. If that filter removes everything, it falls back to the first few raw FTS hits. `_merge_fts_and_vector()` then unions the FTS and vector candidate sets by node id before expansion.
9. `pam.retrieval.graph_expander.expand()` widens the result set:
   - requested relationship queries expand incoming or outgoing edges for the requested relation family
   - `REFERS_TO` edges can pull in traversable entities and the other nodes that refer to those entities
   - draft entities are traversable but not surfaceable top-level results
   - `DERIVED_FROM` and `SUPERSEDES` edges are expanded from note candidates
   - `RELATED` edges are expanded only for `reason` intent
10. `pam.retrieval.ranker.rank_and_assemble()` combines candidate and expanded nodes, scores them, and assembles a `RetrievalResult`.
11. Node scoring combines:
   - transformed BM25 relevance
   - vector cosine similarity (when the query and node both have embeddings)
   - recency from `valid_at`
   - explicit `importance`
   - optional entity-match bonus
12. If the parsed query is relationship-first and names a relation family:
   - inter-result edges are ranked as primary hits
   - the connected nodes for those edges are forced into the returned node set
13. If the parsed query is relationship-oriented but does not name a relation family:
   - node assembly remains primary
   - relationship metadata is still preserved in `query_meta`
   - returned `relationships` come from the final inter-result edges rather than a primary edge-ranking pass
14. Returned nodes have `access_count` incremented.
15. Final inter-result edges are gathered into:
   - `relationships`
   - `conflicts`
   - `superseded`
16. Session groups are built from the returned nodes.
17. `pam.retrieval.search.retrieve()` appends a query log event.
18. The caller receives a `RetrievalResult`, which can then be rendered as:
   - CLI human output
   - CLI JSON output
   - agent context-window text

### Why The Current Flow Is Not Enough

This flow works best when a graph answer can be recovered from lexically retrievable nodes plus one hop of known relations. It is weaker when the question asks for:

- influence rather than explicit mention
- evolution rather than one replacement edge
- central themes rather than a single supporting memory
- adjacent topics rather than stored facts

The main issue is that graph reasoning starts too late. FTS usually decides the candidate set before the graph gets meaningful influence.

### Intended Graph-Native Query Flow

For the personal-memory use case, retrieval should move toward this flow.

1. Parse the raw query into a query plan, not only keyword fields.
2. Identify the requested answer shape:
   - direct lookup
   - explicit relationship
   - influence chain
   - evolution chain
   - theme summary
   - adjacent-topic or gap suggestion
3. Resolve anchors against nodes, entities, aliases, and previously linked concepts.
4. Choose the retrieval strategy based on that plan:
   - lexical-first when the query is literal lookup
   - graph-first or graph-equal when the query is relational, temporal, thematic, or gap-oriented
5. Expand the relevant graph neighborhood with constrained multi-hop traversal and explicit relation-family preferences.
6. Score candidate nodes, edges, and paths together.
7. Assemble an explanation payload that records why the answer won.
8. Return both the answer-bearing nodes and the supporting edges or paths needed for rendering.
9. If the graph is too sparse to answer the question directly, surface the failure mode rather than pretending lexical overlap solved it.

## Ingestion Flow

### Current Baseline

This is the live write path.

1. A caller invokes `cli.py add ...`, `pam.agent_interface.ingest_for_agent(...)`, or `pam.ingestion.pipeline.ingest(...)` directly.
2. `pam.agent_interface.ingest_for_agent()` maps agent input into pipeline input kinds:
   - `kind="source"` becomes `input_type="document"`
   - `kind="event"` becomes `input_type="task"`
   - bare links become `input_type="link"`
   - all other text becomes a note
3. `pam.ingestion.pipeline.ingest()` opens or receives a connection and initializes schema.
4. `pam.ingestion.normalize.normalize()` strips whitespace, validates the input kind, records timestamps, resolves `workspace_id`, and preserves optional `session_id`.
5. `_maybe_warn_session_staleness()` checks the most recently created node in the same session and workspace.
6. `pam.ingestion.extract.extract()` deterministically derives node type, title, content, metadata, and content hash.
7. For URL-backed sources, extraction attempts to fetch content, classify source type, extract HTML text, and reuse the fetched body for dedupe.
8. Dedupe runs against `content_hash` within the resolved workspace and only matches non-archived statuses.
9. If dedupe returns an existing id:
   - ingest returns that id immediately
   - if the input was a source with `parent_note_id`, a `DERIVED_FROM` edge can still be added from the parent note to the existing source
10. If there is no dedupe hit:
   - summary generation runs
   - entity extraction runs
   - per-entity edge facts run
11. The main node is inserted first.
12. If the node type is `event` or `note`, entity linking runs:
   - workspace-local entity candidates are prefiltered with FTS
   - titles and aliases are fuzzy matched
   - new unmatched entities are created as `draft`
   - forward `REFERS_TO` edges are created from the main node to entity nodes
13. If the new note or event shares linked entities with an older active or reference memory and uses strong cue language such as `based on`, `revise`, `replaces`, or `avoid` against an older recommendation:
   - the pipeline can add a cross-memory `DERIVED_FROM`, `SUPERSEDES`, or `CONTRADICTS` edge
   - the edge fact preserves the source sentence that carried the cue
   - `SUPERSEDES` also demotes the older note to `reference`, consistent with the explicit feedback path
   - `CONTRADICTS` is intentionally narrower and currently requires an older shared-entity note with positive or recommendation-style cue language
14. If the node type is `source` and `parent_note_id` is present:
   - the parent note is validated
   - a `DERIVED_FROM` edge is created from note to source
15. The main node insert, node embedding, entity linking, relationship edges, and provenance edges all run inside a single `transaction()` block; if any step fails the transaction rolls back atomically (no partial state survives) and the exception is re-raised.
16. A best-effort ingest log event is appended.

### Intended Graph-Construction Flow

Ingest is where PAM either gains a usable memory graph or stays stuck with note search. The write path should grow toward this flow.

1. Normalize and dedupe as it does today.
2. Classify the new item as note, event, source, entity-bearing observation, correction, plan, or reflection where that distinction matters.
3. Extract entities and concepts, not only named entities.
4. Resolve or create the relevant graph nodes.
5. Write dependable provenance edges first.
6. Write dependable conceptual edges next, such as:
   - references
   - derivation
   - supersession
   - contradiction
   - relatedness with evidence
   - influence or reuse when that claim is supported strongly enough
7. Attach edge facts or explanation text that can later justify the link.
8. Link the new memory into any existing idea chain or correction chain when the evidence is explicit enough.
9. Record enough timestamps and source lineage that evolution queries can be reconstructed later.
10. Emit diagnostics when relation candidates were found but intentionally not written because confidence or rule support was too weak.

The practical rule is simple: ingest should construct as much dependable graph as possible, because retrieval cannot reason over structure that was never written.

## Lifecycle Flow

### Current Baseline

#### Decay

1. A caller invokes `cli.py decay` or `pam.lifecycle.apply_decay(...)`.
2. `apply_decay()` queries the database for all nodes with status `active`, `draft`, or `reference` (the filter is pushed into SQL via `list_nodes(status=ELIGIBLE_STATUSES)`).
3. Pinned nodes at max importance are skipped.
4. `compute_decayed_importance()` applies exponential decay from `updated_at`.
5. Updated importance values are batch-written.
6. Nodes that fall below `ARCHIVE_THRESHOLD` are marked `archived`.
7. `archive` and `decay` log events are appended.

#### Unarchive

1. A caller invokes `cli.py unarchive NODE_ID` or `pam.lifecycle.unarchive(...)`.
2. The node must exist and currently be `archived`.
3. Status is reset to `active`.
4. Importance is reset to the configured default.
5. An `unarchive` lifecycle log event is appended.

### Intended Memory-Evolution Behavior

Lifecycle in a personal-memory system should do more than decay stale notes. It should preserve idea evolution.

That implies:

- current thoughts should outrank old ones without erasing the old chain
- superseded and contradicted memories should stay explainable as historical context
- archived nodes should remain recoverable when a question is explicitly historical
- lifecycle should avoid flattening all old memories into undifferentiated low-importance debris

## Feedback Flow

### Current Baseline

#### Upvote

1. Load node.
2. Clamp and increase importance.
3. Optionally boost listed edge weights.
4. Append an `upvote` log event.

#### Downvote

1. Load node.
2. Clamp and decrease importance.
3. Append a `downvote` log event.

#### Pin

1. Load node.
2. Set importance to max.
3. Append a `pin` log event.

#### Supersede

1. Load old and new nodes.
2. Validate that both are supersedable types: `note` or `entity`.
3. Create a `SUPERSEDES` edge from new to old.
4. If the edge was newly created, reduce the old node's importance by the configured factor.
5. Mark the old node as `reference`.
6. Append a `supersede` log event.

### Intended Role In A Graph-Native Memory

Feedback should tune both node salience and graph quality.

In practice that means:

- user feedback should help clarify which memories are central, not only which are recent
- correction and supersession flows should strengthen the evolution chain rather than only demoting the old node
- future graph-oriented feedback should be able to reinforce or reject specific links when the user knows the graph is wrong

## CLI Flow

### Current Baseline

Shared CLI setup:

1. Open SQLite connection.
2. Initialize schema and compatibility repairs.
3. Store the connection in Click context.
4. Dispatch to the selected command.
5. Close the connection on exit.

Human command surface:

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
- `doctor`
- `rebuild-fts`

Current CLI-specific behaviors:

- `add` requires exactly one of positional text, `--url`, or `--file`
- `--type` only applies to plain-text ingest
- `query` supports `--top` and `--json`
- `stats` reports type counts, status counts, relation counts, and total FTS rows
- `migrate` accepts `--backfill-embeddings` to embed every node missing a vector
- `doctor` reports database health and exits non-zero on drift; `rebuild-fts` wipes and rebuilds the FTS index from `nodes`

### Intended Human Query Experience

For graph-native memory questions, the CLI should be able to show more than ranked notes.

It should eventually render:

- relationship-first answers when the question is relational
- brief explanation chains for influence and evolution prompts
- provenance and supporting memories when the answer depends on sources
- theme summaries backed by the most central nodes and edges
- adjacent-topic suggestions with clear evidence about why they are adjacent rather than invented

## Agent Flow

### Current Baseline

#### Agent Ingest

1. An agent calls `pam.agent_interface.ingest_for_agent(...)`.
2. The helper maps the incoming value to the right ingest kind.
3. It delegates to `pam.ingestion.pipeline.ingest(...)` with optional session, time, workspace, and parent-note context.
4. It returns `AgentIngestResult(node_id=...)`.

#### Agent Query

1. An agent calls `pam.agent_interface.query_for_agent(...)`.
2. That helper delegates to `retrieve(...)`, optionally with a workspace override.
3. The caller may render the result through `format_for_context_window(...)`.
4. The formatter groups output into stable sections for events, notes, sources, entities, conflicts, superseded links, and relationships, and it places relationships first only when the retrieval result is in relationship-answer mode and explicit relationship hits were returned.
5. If the rendered block exceeds the context budget, trailing lines are dropped and a `[truncated]` marker is appended.

### Intended Agent Experience

The agent-facing boundary should stay stable, but the context it emits should become more graph-native.

That means agent retrieval should increasingly surface:

- the winning edges or paths, not only the winning nodes
- the reason a memory is central or adjacent
- evolution chains for "how did this change" prompts
- enough structured context that an answering agent does not have to rediscover the graph in free text

## Failure And Fallback Matrix

### Query Parsing

- Missing SDK: deterministic fallback, no warning.
- Invalid JSON: deterministic fallback, warning.
- Unexpected exception: deterministic fallback, warning.

### Ingestion LLM Helpers

- Missing SDK: empty summary, entity list, or edge fact, no warning.
- Invalid entity JSON: empty entity list, warning.
- Other exception: empty output, warning.

### URL Fetch

- network or parse failure: source falls back to hostname and raw URL content.

### Duplicate Writes

- duplicate edges: safe no-op return value.
- duplicate content hash within a workspace: existing node id returned.

### Missing Graph Structure

This is the important failure class the old docs understated.

When PAM fails on an influence, evolution, theme, or gap query, the root cause may be one of three different things:

- the graph relation was never written at ingest time
- the graph relation exists but retrieval did not traverse or rank it well
- the graph relation exists and was traversed, but the formatter failed to expose it clearly

Future evaluation and operator tooling should distinguish those cases explicitly.
