# PAM Module: Ingestion Pipeline
### `pam/ingestion/` - `pipeline.py`, `normalize.py`, `extract.py`, `llm.py`, `entity_linker.py`
> Owner: Agent 2 | Depends on: `pam.db`, `config.py` | Depended on by: `cli.py`, `pam.agent_interface`

---

## 1. Role

The ingestion layer owns the write path from raw input to persisted nodes and edges.

Current baseline:

- validate and normalize input
- perform deterministic extraction and dedup
- call optional LLM helpers
- create the main node
- link named entities
- create deterministic relationship edges from shared entities and co-mentioned concepts
- infer narrow explicit `DERIVED_FROM`, `SUPERSEDES`, and `CONTRADICTS` links when strong cue phrases point at a shared-entity neighbor
- create note-to-source provenance edges
- emit ingestion logs

Intended implementation:

- construct the graph that retrieval will later reason over
- preserve idea evolution, provenance, correction, contradiction, and high-value conceptual connections
- make graph quality a first-class ingestion concern rather than a side effect of entity extraction

The package export surface is defined in `pam/ingestion/__init__.py`.

---

## 2. Current Public Surface

### 2.1 `normalize.py`

Public exports:

- `VALID_INPUT_TYPES`
- `normalize(raw_text, input_type, provided_at=None, session_id=None, workspace_id=None)`

`normalize()` returns a canonical dictionary with:

```python
{
    "raw_text": str,
    "input_type": "note" | "link" | "task" | "document",
    "provided_at": datetime,
    "recorded_at": datetime,
    "session_id": str | None,
    "workspace_id": str,
}
```

Key behavior:

- trims and validates non-empty input
- lowercases and validates `input_type`
- normalizes timestamps to UTC
- defaults `provided_at` to `recorded_at`
- resolves `workspace_id` to an absolute path string

### 2.2 `extract.py`

Public exports:

- `FetchedSource`
- `TITLE_MAX_LENGTH`
- `compute_content_hash(raw_text)`
- `normalize_whitespace(text)`
- `infer_node_type(input_type, explicit_node_type=None)`
- `extract(normalized, node_type=None, url=None, parent_note_id=None, conn=None)`

`extract()` performs deterministic field derivation and dedup before any LLM call.

Important current behavior:

- supported explicit node types are `event`, `note`, and `source`
- type inference maps `link -> source`, `task -> event`, `note -> note`, `document -> source`
- source ingestion with a URL attempts to fetch the remote content first, then computes the content hash from the fetched content or fallback content
- dedup is workspace-scoped through `find_by_content_hash(..., workspace_id=normalized["workspace_id"])`
- the returned extracted payload includes `parent_note_id` and `workspace_id` for later pipeline steps

Current default metadata shapes:

- `event`: `{"duration_minutes": None, "source": "manual"}`
- `note`: `{"is_belief": False, "confidence": 1.0}`
- `source`: `{"url": url_or_empty, "content_type": detected_type}`

`FetchedSource` is the structured fetch result used for URL-backed sources:

```python
@dataclass
class FetchedSource:
    title: str
    content: str
    content_type: Literal["article", "documentation", "paper", "video", "other"]
```

### 2.3 `llm.py`

Public exports:

- `LLMUnavailableError`
- `summarize(content)`
- `extract_entities(content)`
- `generate_edge_fact(content, entity_name)`

Important behavior:

- provider selection comes from `config.py`
- missing local SDKs raise `LLMUnavailableError` internally and are converted into safe fallbacks
- `summarize()` returns `""` on failure
- `extract_entities()` returns `[]` on failure and filters entities to the configured categories and max count
- `generate_edge_fact()` returns `""` on failure

Current limitation:

- LLM helpers still do not extract explicit cross-entity relations directly; the richer relationship graph is currently built through deterministic post-linking steps in the pipeline

### 2.4 `entity_linker.py`

Public exports:

- `LinkEntitiesResult`
- `link_entities_detailed(conn, node_id, entities, edge_facts, content, workspace_id=None)`
- `link_entities(conn, node_id, entities, edge_facts, content, workspace_id=None)`

`LinkEntitiesResult` is the detailed linking summary:

```python
@dataclass
class LinkEntitiesResult:
    entity_ids: list[str]
    linked_existing: int
    created_new: int
```

Important behavior:

- existing entity candidates are pre-filtered with `fts_search_entities()` inside the same workspace
- matching uses `rapidfuzz` when available and `SequenceMatcher` otherwise
- new entities are created as `draft` nodes with metadata `{"aliases": [name], "category": category}`
- `REFERS_TO` edges are created only after the main node already exists

### 2.5 `pipeline.py`

Public exports:

- `ingest(raw_text, input_type="note", session_id=None, provided_at=None, node_type=None, url=None, workspace_id=None, parent_note_id=None, force_session=False, conn=None)`

This is the single write orchestrator used by both the CLI and the agent interface.

---

## 3. Live Pipeline Order

The current pipeline order is:

1. `initialize(conn)`
2. `normalize(...)`
3. session staleness warning check
4. `extract(...)`
5. short-circuit on dedup hit
6. `summarize(...)`
7. `extract_entities(...)`
8. `generate_edge_fact(...)` for each extracted entity
9. create the main node
10. link entities for `event` and `note` nodes
11. create deterministic `RELATED` edges between memories that now share linked entities
12. create deterministic `RELATED` edges between co-mentioned entity nodes
13. infer `DERIVED_FROM`, `SUPERSEDES`, or `CONTRADICTS` for the new memory when explicit cue language matches a nearby shared-entity memory strongly enough
14. create `DERIVED_FROM` when a source has `parent_note_id`
15. append ingestion log event

The main node is intentionally created before entity linking. That ordering is required because `edges` enforces foreign keys and `REFERS_TO` edges point back to the main node.

---

## 4. What The Current Pipeline Actually Produces

The live pipeline is good at producing:

- normalized memory records
- dedup-safe writes
- note-to-entity references
- note-to-note and note-to-source relatedness when memories share linked entities
- concept-to-concept relatedness when multiple entities are co-mentioned in one memory
- note-to-source provenance
- explicit correction chains when the user later calls `supersede()`
- narrow cue-based derivation, revision, replacement, and contradiction links when a new note explicitly says it is based on, revises, replaces, or rejects a nearby shared-entity memory

It is not yet good enough at producing:

- influence chains between ideas
- architectural relationships between workstreams
- explicit evidence for why two memories should be treated as adjacent topics

That gap is narrower than before. Ingestion now creates a dependable baseline graph for shared-entity adjacency plus a small amount of explicit cross-memory derivation, supersession, and contradiction, but it still does not infer broader influence chains or richer architectural relationships without stronger write-time rules.

That distinction is the main reason retrieval still behaves more like note search than graph-native memory reasoning.

---

## 5. Required Ingestion Work For A Graph-Native Memory

### 5.1 Move Beyond Named-Entity Linking

Entity linking is useful, but personal-memory questions are often about concepts and ideas rather than named people or tools.

Examples of graph elements ingestion should learn to create more reliably:

- project concepts such as memory routing, retrieval planning, or MCP orchestration
- durable themes such as local-first design, observability, or agent tooling
- evolving plans and corrections across multiple notes

The practical rule is not "extract more things blindly." It is "extract graph nodes that will later support explanation-quality answers."

### 5.2 Create More Dependable Cross-Memory Edges

The current pipeline mostly creates `REFERS_TO` and `DERIVED_FROM`. For the intended use case it should also create dependable cross-memory links when the evidence is strong enough.

Important categories include:

- idea derived from a source or prior note
- one note superseding or correcting another
- one note contradicting another
- two memories belonging to the same theme or workstream
- one memory influencing another
- one system component complementing another in an architecture

These links do not have to become a huge uncontrolled ontology immediately. The near-term requirement is just that ingest writes more of the graph PAM will later need.

### 5.3 Preserve Edge Evidence

Graph-native retrieval depends on being able to explain a link.

That means each inferred edge should preserve enough evidence to answer later questions like:

- why do we believe note A influenced note B
- what text connected this note to that concept
- why is this topic adjacent rather than central

Today edge facts exist for entity mentions. The same design principle needs to extend to richer conceptual links.

### 5.4 Capture Thought Evolution

The personal-memory use case depends on temporal and causal reasoning.

Ingest should therefore preserve:

- when a note was recorded versus when it was valid
- whether it corrected or extended prior thinking
- whether it came from a source, experiment, reflection, or implementation step
- enough chain structure that retrieval can reconstruct "how did my thinking evolve" without guessing

### 5.5 Keep Graph Quality Higher Than Graph Quantity

The wrong graph is worse than a sparse graph.

Implementation rules should favor:

- deterministic links first
- model-assisted links only when they are grounded and explainable
- explicit provenance for inferred links
- the option to decline writing a weak relation rather than forcing every nearby note into a graph edge

---

## 6. Dedup And Source Handling

### 6.1 Dedup

Dedup happens in `extract()` before any LLM call.

- dedup uses the normalized content hash
- dedup is workspace-scoped
- dedup only matches nodes whose status is `active`, `draft`, or `reference`

This should remain true even as graph construction gets richer.

### 6.2 Source Inputs

For source-like inputs:

- `input_type="link"` or `input_type="document"` maps to node type `source` unless overridden
- URL fetch is attempted with `urllib.request` and a `PAM/1.0` user-agent
- HTML responses use title extraction plus visible-text extraction
- non-HTML responses use the hostname as title and normalized body text as content
- when fetch fails, the pipeline falls back to the hostname or raw URL

### 6.3 `DERIVED_FROM`

`parent_note_id` is only meaningful for sources.

- on a fresh source ingest, the source node is created and then `parent_note_id -> source_id` is inserted as `DERIVED_FROM`
- on a dedup hit for a source ingest, the pipeline still validates `parent_note_id` and still creates the `DERIVED_FROM` edge to the already-existing source node

This is one of the stronger graph behaviors already implemented today and should be treated as the model for other dependable relation writes.

---

## 7. Session And Failure Semantics

### 7.1 Session staleness

The warning check is workspace-scoped and compares the new record's `recorded_at` against the most recent node's `created_at` in the same session.

The check warns through the logger and never aborts ingestion.

### 7.2 Failure cleanup

After the main node is inserted, later linking work is wrapped in a cleanup block.

- if entity linking fails, the just-created node is deleted
- if `parent_note_id` validation fails after node creation, the just-created node is deleted

That keeps the graph from retaining partially-ingested nodes.

As graph construction gets richer, PAM will need broader transaction boundaries so partially-written conceptual edges do not survive failed ingests.

---

## 8. Invariants To Preserve

- all writes go through `ingest()`
- `normalize()` must always return UTC timestamps and resolved `workspace_id`
- `extract()` must remain deterministic and LLM-free
- the main node must exist before any dependent edge is emitted
- entity linking is only run for `event` and `note` nodes today
- LLM failures degrade to empty summaries, empty entity lists, and empty edge facts rather than failing the ingest
- graph-native enrichment should prefer dependable explicit links over speculative link inflation
