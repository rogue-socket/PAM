# PAM Module: Retrieval Layer
### `pam/retrieval/` - `query_parser.py`, `search.py`, `graph_expander.py`, `ranker.py`
> Owner: Agent 3 | Depends on: `pam.db`, `config.py` | Depended on by: `cli.py`, `pam.agent_interface`

---

## 1. Role

The retrieval layer owns the read path from a raw query string to a `RetrievalResult`.

Current baseline:

- parse user intent
- run workspace-scoped FTS
- expand nearby graph structure
- rank nodes, explicit relationship hits, or inferred support paths
- increment access counts for surfaced nodes
- log the query

Intended implementation:

- plan graph-native retrieval strategies for different question shapes
- treat edges and paths as first-class answer objects
- explain idea evolution, influence, themes, and adjacent topics with explicit graph evidence

The package export surface is defined in `pam/retrieval/__init__.py` and currently re-exports `ParsedQuery`, `parse_query`, `RetrievalResult`, and `retrieve`.

---

## 2. Current Public Surface

### 2.1 `query_parser.py`

The live query contract is:

```python
@dataclass
class ParsedQuery:
    keywords: list[str]
    entities: list[str]
    time_range: dict[str, str | None] | None
    intent: Literal["lookup", "timeline", "summarize", "reason"]
    relation_filters: list[str] = field(default_factory=list)
    relation_direction: Literal["incoming", "outgoing", "both"] | None = None
    answer_mode: Literal["node", "relationship"] = "node"
    question_shape: Literal["lookup", "relationship", "influence", "evolution", "theme", "gap"] = "lookup"
    anchor_terms: list[str] = field(default_factory=list)
    time_range_relative: bool = False
```

Public exports:

- `ParsedQuery`
- `VALID_ANSWER_MODES`
- `VALID_QUESTION_SHAPES`
- `VALID_INTENTS`
- `VALID_RELATIONS`
- `VALID_RELATION_DIRECTIONS`
- `STOP_WORDS`
- `fallback_parse(query, today=None)`
- `parse_query(raw_query, today=None)`
- `parse_query_with_metadata(raw_query, today=None)`

Important current behavior:

- `parse_query_with_metadata()` returns `(parsed_query, llm_fallback_used)`
- LLM parsing asks for relation filters, relation direction, answer mode, question shape, and anchor terms in addition to keywords, entities, time range, and intent
- deterministic fallback infers:
  - time ranges from explicit dates and phrases like `today`, `yesterday`, `last week`, and `this week`
    - relation filters from relation-language and graph-question heuristics
  - relation direction for `REFERS_TO`, `DERIVED_FROM`, and `SUPERSEDES`
  - answer mode (`node` vs `relationship`)
    - question shape (`lookup`, `relationship`, `influence`, `evolution`, `theme`, `gap`)
  - anchor terms from capitalized tokens
- missing or invalid LLM relation fields are backfilled from deterministic heuristics instead of being dropped
- generic relationship language can set `answer_mode="relationship"` even when no specific relation family was inferred
- invalid or missing LLM fields are normalized rather than trusted blindly

The key limitation is no longer question-shape detection itself. The current gap is that these shapes still drive mostly shallow one-hop retrieval behavior rather than a deeper graph planner.

### 2.2 `search.py`

Public exports:

- `fts_search_with_filter(conn, parsed, workspace_id=None)`
- `retrieve(raw_query, top_k=None, workspace_id=None)`

Important current behavior:

- FTS is always scoped through the resolved workspace ID when one is supplied
- time filters apply to `valid_at`
- `fts_search_with_filter()` applies a precision filter after raw FTS
- if the precision filter removes everything, strong anchor terms can seed a fallback candidate pass before the function falls back to the first five raw FTS candidates
- when FTS returns no candidates at all and the query carries a time range, a final fallback pulls all nodes within `parsed.time_range` — or the most-recent nodes when the time phrase was relative (`time_range_relative`) and nothing matched the window
- alongside FTS, `retrieve()` also runs `vector_search()` (query embedding → nearest `vec_nodes` rows) and `_merge_fts_and_vector()` unions both candidate sets before expansion; `vector_search()` returns nothing when embeddings are unavailable, so retrieval degrades cleanly to FTS-only
- `retrieve()` opens an initialized connection, parses the query, runs retrieval, logs the request, and closes the connection

This is still the main retrieval bottleneck for graph-native behavior. Candidate recall is lexical plus vector similarity, with anchor rescue as a narrow fallback rather than a full graph-first planner.

### 2.3 `graph_expander.py`

Public exports:

- `ExpandedPath`
- `ExpandedPathSegment`
- `ExpandedResult`
- `expand(conn, candidates, parsed)`

```python
@dataclass
class ExpandedResult:
    nodes: list[Node]
    edge_facts: dict[tuple[str, str], str]
    entity_boosted_ids: set[str]
    support_paths: list[ExpandedPath] = field(default_factory=list)
```

Important current behavior:

- requested-relationship expansion happens first when `parsed.relation_filters` is non-empty
- relationship expansion honors `relation_direction` and `EDGE_WEIGHT_EXPANSION_THRESHOLD`
- entity boosting still comes from `REFERS_TO` edges that connect candidate nodes to parsed entities
- draft entities are traversable during entity expansion, but only active nodes are usually surfaced
- shared draft-entity bridges are now preserved as support paths even when the bridge node itself is not surfaced
- gap queries can preserve nearby one-hop concept evidence even when only one surfaced node currently mentions that concept
- `REFERS_TO -> RELATED(entity) -> REFERS_TO` chains can now surface connected memories and support-path explanations for relationship-heavy queries
- `SUPERSEDES` expansion is allowed to surface `reference` nodes
- `RELATED` concept expansion is enabled for `intent == "reason"` or explicit `RELATED` relation queries

This gives PAM path-aware one-hop relation reasoning, shared-entity bridge preservation, and simple entity-chain traversal. It still does not provide a general multi-hop traversal planner or a true graph search frontier.

### 2.4 `ranker.py`

The live result contract is:

```python
@dataclass
class RetrievalResult:
    events: list[Node]
    entities: list[Node]
    notes: list[Node]
    sources: list[Node]
    conflicts: list[tuple[str, str]]
    superseded: list[tuple[str, str]]
    edge_facts: dict[tuple[str, str], str]
    session_groups: dict[str, list[str]]
    query_meta: dict[str, Any]
    ordered_nodes: list[Node] = field(default_factory=list)
    relationships: list[Edge] = field(default_factory=list)
    graph_explanations: list[GraphExplanation] = field(default_factory=list)
    score_components: dict[str, dict[str, float]] = field(default_factory=dict)
```

Public exports:

- `GraphExplanation`
- `GraphPathSegment`
- `RetrievalResult`
- `days_since(dt, now)`
- `score(node, fts_rank, entity_boost, now, vector_similarity=None) -> (total, components)`
- `rank_and_assemble(conn, candidates, expanded, parsed, top_k=None, vector_similarities=None)`

Important current behavior:

- ranking combines text relevance, vector similarity, recency, importance, and optional entity bonus
- `ordered_nodes` preserves the final ranked node order
- `relationships` is now a first-class result field
- `query_meta` now carries `question_shape` and `anchor_terms` alongside intent and relation metadata
- `graph_explanations` now surfaces compact path, bridge, cluster, and sparse-evidence summaries for downstream renderers
- `score_components` carries per-node `{text_relevance, vector_similarity, recency, importance, entity_bonus}` post-weight contributions for nodes in `ordered_nodes`; the five entries sum to the rank-key under the same float arithmetic, plus an optional `derived_propagation` entry when the `DERIVED_FROM` score-propagation path fires
- in relationship mode, edges are ranked first and nodes are selected around those edges
- when explicit relationship hits are absent, support paths can still drive node ordering for influence, connection, theme, gap, and evolution prompts
- direct connection paths can now be inferred from entity-to-entity `RELATED` chains instead of only explicit note-to-note edges
- evolution queries now surface a simple time-ordered sequence summary from the retrieved nodes
- theme and gap summaries now use bridge-concept frequency as a lightweight current-baseline heuristic
- in normal node mode, `relationships` contains all inter-edges among the surfaced nodes
- access counts are incremented only for final surfaced nodes

This is stronger than the older node-only retriever, but it is still limited to short explanation payloads and heuristic cluster summaries rather than true multi-hop path-native or centrality-native ranking.

---

## 3. Retrieval Problems This Module Must Solve

For the personal-memory use case, the retrieval layer needs to answer five hard classes of question:

- direct lookup
- explicit relationship lookup
- influence or provenance tracing
- idea evolution over time
- central-theme and adjacent-topic discovery

The current code mainly solves the first two well and solves narrow slices of the third and fourth when explicit edges already exist.

The weak points are:

- relation supply is thin, so graph traversal often has little to work with
- candidate selection is still FTS-led, so graph-heavy questions still depend on lexical recall despite anchor fallback
- generic graph questions now classify more accurately, but still do not drive a richer retrieval plan than one-hop expansion plus support-path assembly
- result assembly exposes compact explanations, but not yet robust multi-hop paths, centrality-based clusters, or principled missing-edge diagnoses

---

## 4. Current Retrieval Flow

The live flow is:

1. `parse_query_with_metadata(raw_query)`
2. resolve workspace scope
3. `fts_search_with_filter(...)` and `vector_search(...)`, merged by `_merge_fts_and_vector(...)`
4. `expand(...)`
5. `rank_and_assemble(...)`
6. append query log event

The query log records the raw query, workspace ID, normalized query metadata, fallback usage, candidate counts, expansion counts, returned node IDs, conflict count, and duration.

This flow is accurate, but it underspecifies the strategic limitation: the graph is mostly downstream of FTS.

---

## 5. Graph-Native Retrieval Design

### 5.1 Query classes PAM should recognize

The retrieval planner should increasingly distinguish at least these answer shapes:

- `lookup`: direct factual retrieval
- `relationship`: explicit typed relation lookup
- `evolution`: how a plan, idea, or belief changed
- `influence`: what sources or prior memories shaped a later memory
- `theme`: what concepts are central across a set of memories
- `gap`: what nearby topics look underexplored

These do not all need to become public enum values immediately, but retrieval needs an internal plan expressive enough to drive them.

### 5.2 Candidate selection should stop being purely lexical

For graph-heavy queries, the ideal order is:

1. resolve anchors against nodes, entities, aliases, and concepts
2. prefer direct graph neighborhoods when anchors are strong
3. use FTS to widen or rescue recall, not to decide the whole search frontier
4. keep lexical fallback when the graph is sparse or the prompt is literal

### 5.3 Expansion should become path-aware

The current expander mostly collects reachable nodes. The next version needs to preserve more structure about how those nodes were reached.

At minimum, it should support:

- constrained multi-hop traversal for explicit graph questions
- relation-family preferences driven by the query plan
- path recording so later ranking can score explanations, not only endpoints
- distinction between traversable bridge nodes and answer-bearing nodes

### 5.4 Ranking should consider paths, not only endpoints

For graph-native answers, the winning object may be:

- one edge
- a short path
- a cluster of related nodes
- a ranked set of adjacent topics

That means the ranking model needs features like:

- path length and path quality
- relation specificity
- supporting source provenance
- temporal continuity or correction sequence
- centrality within a local cluster
- novelty versus already-central themes for gap questions

### 5.5 Result assembly should expose explanations directly

The result contract already exposes `relationships`. That is a strong baseline.

The next step is to add enough explanation structure that downstream renderers can answer without reconstructing the graph from scratch. Likely additions over time include:

- primary supporting paths
- explanation labels
- cluster summaries
- missing-edge or fallback diagnostics

---

## 6. Precision Filtering And Expansion Rules Today

### 6.1 Precision filtering

`search.py` applies an overlap-based precision filter after FTS.

The filter considers:

- normalized keyword overlap
- stronger requirements for broader keyword sets
- anchor-term matches
- time and relation constraints

This is why retrieval is stricter than a plain FTS pass. It is also why graph-heavy queries can still fail when the right anchors are semantically nearby but lexically weak.

### 6.2 Graph expansion rules

Current expansion behavior is more nuanced than the older docs implied.

- requested relationship expansion can traverse incoming, outgoing, or both directions
- event and note candidates expand through `REFERS_TO` to entity nodes and then back through reverse `REFERS_TO` edges to related notes and events
- note candidates expand through `DERIVED_FROM` to source nodes
- note candidates expand through `SUPERSEDES` to older nodes, including `reference` nodes
- `RELATED` concept-chain expansion fires for `intent == "reason"` or when `RELATED` is explicitly in `relation_filters`; direct outgoing-`RELATED` expansion is reserved for `intent == "reason"`

`CONTRADICTS` is not used for traversal. It is surfaced later as part of result assembly.

---

## 7. Relationship Answers Today

Relationship-aware retrieval is already a first-class mode.

When `parsed.answer_mode == "relationship"` and `parsed.relation_filters` is non-empty:

- inter-node edges are ranked by edge weight, supporting node scores, direction match, and presence of an edge fact
- the top relationship hits are returned in `result.relationships`
- nodes are then selected around those relationships and exposed through the normal node buckets plus `ordered_nodes`

When `parsed.answer_mode == "relationship"` but `parsed.relation_filters` is empty:

- retrieval keeps the relationship-oriented metadata in `query_meta`
- node assembly stays primary
- `result.relationships` comes from inter-edges among the surfaced nodes rather than a ranked primary relationship list

When retrieval is not in relationship mode, `result.relationships` still contains the inter-edges among surfaced nodes. This keeps relationship context available to the CLI and agent formatter even for normal node-centric queries.

The important stale-doc fix is this: PAM already has relation-aware retrieval, but it does not yet have graph-native reasoning for the harder question classes.

---

## 8. File-Specific Implementation Focus

### `query_parser.py`

Keep:

- deterministic fallback
- relation-family inference
- answer-mode normalization

Add next:

- stronger query-shape detection for evolution, influence, themes, and gaps
- clearer separation between lexical lookup intent and graph reasoning intent
- better anchor extraction for concept phrases, not only capitalized terms

### `search.py`

Keep:

- workspace scoping
- time filtering on `valid_at`
- query logging

Add next:

- graph-aware candidate strategies
- diagnostics for candidate recall failures
- less dependence on raw keyword overlap when graph intent is explicit

### `graph_expander.py`

Keep:

- requested-relation expansion first
- traversable draft entities
- provenance and supersession expansion

Add next:

- path recording
- constrained multi-hop expansion
- better support for theme and adjacency exploration

### `ranker.py`

Keep:

- node scoring baseline
- first-class `relationships`
- relationship-first explicit path for concrete relation queries

Add next:

- path scoring
- cluster or theme scoring
- richer explanation payloads
- explicit separation between lexical rescue and graph-native wins

---

## 9. Invariants To Preserve

- retrieval must work without the LLM
- time filtering must continue to use `valid_at`
- workspace scope must be carried through parse, search, and expansion
- access counts should only be incremented for returned nodes
- `query_meta` should reflect the normalized query contract actually used by ranking
- `relationships` is part of the public result contract and should not be treated as a compatibility extra
- graph-native answers must stay grounded in stored evidence rather than opaque model assertions

---

## 10. Recommended Implementation Sequence

1. Improve ingest-time relation supply so retrieval has more dependable graph to work with.
2. Extend query planning for evolution, influence, theme, and gap prompts.
3. Make graph-aware candidate selection explicit in `search.py`.
4. Add path-aware expansion and ranking.
5. Extend the result contract and renderers with explanation payloads.
