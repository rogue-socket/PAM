# PAM Module: Database Layer
### `pam/db/` - `schema.py`, `nodes.py`, `edges.py`, `fts.py`
> Owner: Agent 1 | Depends on: `config.py` | Depended on by: all higher layers

---

## 1. Role

The database layer owns persistence, schema management, and storage-oriented query helpers. It does not implement ingestion policy, retrieval policy, lifecycle rules, or CLI behavior. Every module that needs SQLite should come through this layer instead of opening ad hoc connections.

For the updated product framing, the DB layer is not just a persistence utility. It is the graph substrate that makes graph-native personal memory possible.

The live package export surface is defined in `pam/db/__init__.py` and re-exports the node, edge, FTS, and schema helpers.

---

## 2. Current Public Surface

### 2.1 `schema.py`

`schema.py` provides:

- `utcnow()`
- `datetime_to_iso(value)`
- `utcnow_iso()`
- `iso_to_datetime(value)`
- `get_connection(db_path=None)`
- `get_initialized_connection(db_path=None)`
- `resolve_workspace_id(workspace_id=None)`
- `initialize(conn)`
- `apply_migrations(conn)`
- `get_current_version(conn)`
- `check_database_health(conn)`
- `MIGRATIONS`

`get_connection()` is the canonical connection factory. It enables WAL mode, foreign keys, a busy timeout, and `sqlite3.Row` access.

`resolve_workspace_id()` normalizes workspace scope to an absolute path string. When the caller does not pass a workspace, the current working directory is used.

`initialize()` does two things:

1. creates `schema_version` and applies pending migrations
2. runs compatibility repair for existing databases, including adding and backfilling `workspace_id` when needed

`check_database_health()` is a storage-level consistency check for the `nodes` table and the standalone FTS index. `get_initialized_connection()` invokes it lazily — once per process per resolved DB path (cached in `_HEALTH_CHECKED_PATHS`) — and logs a `WARNING` via the `pam.db.schema` logger when drift is detected (missing or orphaned FTS rows). The check never raises, so callers that handle their own connections (for example, the eval suites) can still call `check_database_health()` directly when they need to assert health rather than just observe it.

### 2.2 `nodes.py`

`nodes.py` defines the live `Node` dataclass:

```python
@dataclass
class Node:
    id: str
    type: Literal["event", "entity", "note", "source"]
    title: str
    content: str
    summary: str
    content_hash: str
    created_at: datetime
    valid_at: datetime
    updated_at: datetime
    tags: list[str]
    session_id: str | None
    importance: float
    access_count: int
    status: Literal["active", "draft", "reference", "archived"]
    metadata: dict
    workspace_id: str | None = None
```

Public helpers:

- `create_node(conn, node)`
- `get_node(conn, node_id)`
- `update_node(conn, node_id, **fields)`
- `delete_node(conn, node_id)`
- `list_nodes(conn, type=None, status=None, session_id=None, workspace_id=None, since=None, limit=100)`
- `find_by_content_hash(conn, content_hash, workspace_id=None)`
- `increment_access_count(conn, node_id)`
- `update_importance(conn, node_id, new_importance)`
- `bulk_update_importance(conn, updates)`
- `row_to_node(row)`

Behavioral details that matter to other modules:

- `create_node()` generates a UUID when `node.id` is empty
- `create_node()` resolves `workspace_id` before insert
- `update_node()` only accepts fields listed in `UPDATABLE_FIELDS` and always refreshes `updated_at`
- `list_nodes()` sorts by `valid_at DESC, created_at DESC`
- `list_nodes(..., since=...)` filters on `valid_at`, not `created_at`
- `find_by_content_hash()` only returns nodes with status `active`, `draft`, or `reference`
- `update_importance()` and `bulk_update_importance()` both refresh `updated_at`

### 2.3 `edges.py`

`edges.py` defines the live `Edge` dataclass:

```python
@dataclass
class Edge:
    source_id: str
    target_id: str
    relation: Literal["REFERS_TO", "DERIVED_FROM", "RELATED", "CONTRADICTS", "SUPERSEDES"]
    weight: float
    fact: str
    created_at: datetime
```

Public helpers:

- `create_edge(conn, edge)`
- `get_edges_from(conn, node_id, relation=None)`
- `get_edges_to(conn, node_id, relation=None)`
- `get_edges_between(conn, node_ids, relations=None)`
- `update_edge_weight(conn, source_id, target_id, relation, delta)`
- `delete_edges_for_node(conn, node_id)`
- `row_to_edge(row)`

Important behavior:

- `create_edge()` returns `False` for duplicate primary-key inserts instead of raising
- edge weights are clamped into `[0.0, 1.0]`
- `update_edge_weight()` is a no-op when the edge does not exist

### 2.4 `fts.py`

Public helpers:

- `fts_search(conn, query_string, status="active", workspace_id=None, time_start=None, time_end=None, limit=50)`
- `fts_search_entities(conn, entity_name, limit=20, workspace_id=None)`

Important behavior:

- FTS queries are sanitized through `_build_safe_match_query()` before they hit SQLite
- `fts_search()` joins FTS rows back to `nodes`, filters by `status`, `workspace_id`, and `valid_at`, and returns `(node, fts_rank)` tuples
- `fts_search_entities()` only returns nodes of type `entity`

---

## 3. What The Current Schema Gives PAM

The current schema already gives PAM a useful personal-memory substrate:

- durable nodes for notes, events, entities, and sources
- durable edges for provenance, reference, contradiction, relatedness, and supersession
- explicit timestamps for both write time and validity time
- workspace partitioning
- FTS for lexical lookup and anchor resolution

That is enough to support a relation-aware baseline.

It is not yet enough to fully support graph-native reasoning without stronger write-time relation supply and possibly richer edge representation over time.

---

## 4. Schema And Storage Invariants

### 4.1 Nodes schema

The current nodes table includes `workspace_id` as a first-class column:

```sql
CREATE TABLE IF NOT EXISTS nodes (
    id           TEXT PRIMARY KEY,
    type         TEXT NOT NULL CHECK(type IN ('event','entity','note','source')),
    title        TEXT NOT NULL,
    content      TEXT NOT NULL DEFAULT '',
    summary      TEXT NOT NULL DEFAULT '',
    content_hash TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    valid_at     TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    tags         TEXT NOT NULL DEFAULT '[]',
    session_id   TEXT,
    importance   REAL NOT NULL DEFAULT 0.5 CHECK(importance >= 0.0 AND importance <= 1.0),
    access_count INTEGER NOT NULL DEFAULT 0,
    status       TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','draft','reference','archived')),
    metadata     TEXT NOT NULL DEFAULT '{}',
    workspace_id TEXT NOT NULL DEFAULT ''
);
```

Indexes include `idx_nodes_workspace_id` in addition to the type, status, time, session, and `content_hash` indexes.

### 4.2 Edges schema

Edges still use `(source_id, target_id, relation)` as the primary key and keep `ON DELETE CASCADE` on both node references.

### 4.3 FTS schema

The FTS table is still standalone and trigger-synchronized:

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS fts_index USING fts5(
    node_id UNINDEXED,
    title,
    content,
    summary,
    tokenize='porter unicode61'
);
```

This remains intentionally decoupled from SQLite rowid-based external-content mode.

---

## 5. Storage Implications Of A Graph-Native Memory

The current DB layer does not need to become a graph database product. SQLite is still a reasonable storage boundary. But the storage contract does need to support richer reasoning.

Important implications:

- edges must be treated as first-class durable evidence, not ephemeral retrieval hints
- timestamps and provenance must remain queryable enough to reconstruct evolution chains
- if richer relation semantics are added, they should be stored explicitly and migration-safe
- if explanation paths are cached or materialized later, they must remain clearly secondary to the authoritative node and edge store

The near-term lesson is not "replace SQLite." It is "use the existing SQLite graph more deliberately and extend it carefully when the data model proves too narrow."

---

## 6. Workspace Partitioning

Workspace scoping is part of the storage contract.

- inserts resolve and persist `workspace_id`
- dedup can be limited to a workspace through `find_by_content_hash(..., workspace_id=...)`
- `list_nodes()` can filter by workspace
- FTS search and entity FTS search can filter by workspace
- `initialize()` backfills older rows so legacy databases still participate correctly

Other layers should treat `workspace_id` as the boundary for memory separation, not as presentation metadata.

For graph-native retrieval this is even more important, because cross-workspace contamination would not only surface the wrong note. It would also create the wrong relation structure.

---

## 7. What This Layer Does Not Do

The DB layer does not:

- decide ingestion order
- decide retrieval ranking or graph expansion
- apply lifecycle decay policy
- parse CLI arguments
- call LLMs

It provides durable primitives. Higher layers own policy.
