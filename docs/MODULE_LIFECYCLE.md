# PAM Module: Lifecycle & Feedback
### `pam/lifecycle.py`, `pam/feedback.py`, `pam/relations.py`
> Owner: Agent 4 | Depends on: `pam.db`, `config.py` | Depended on by: `cli.py`, `pam.ingestion.pipeline`

---

## 1. Role

The lifecycle and feedback modules own long-term memory maintenance.

- `lifecycle.py` decays importance over time, archives weak nodes, restores archived nodes, and logs lifecycle events
- `feedback.py` applies user feedback, adjusts edge weights when appropriate, creates supersession links, and logs those changes

These modules do not ingest new content or run retrieval.

For the intended personal-memory design, their real job is broader: preserve the user's evolving thinking without losing the historical graph needed to explain how ideas changed.

---

## 2. Current Public Surface

### 2.1 `lifecycle.py`

Public exports:

- `compute_decayed_importance(node, now)`
- `apply_decay(conn)`
- `unarchive(conn, node_id)`

Current constants-in-use come from `config.py`:

- `DECAY_LAMBDA`
- `ARCHIVE_THRESHOLD`
- `IMPORTANCE_DEFAULT`
- `IMPORTANCE_MAX`
- `IMPORTANCE_MIN`

Important current behavior:

- `ELIGIBLE_STATUSES` is the tuple `("active", "draft", "reference")`
- `compute_decayed_importance()` leaves pinned nodes at `IMPORTANCE_MAX`
- decay uses `updated_at`, not `valid_at`
- `apply_decay()` batch-updates importance with `bulk_update_importance()` and then archives nodes whose decayed importance falls below `ARCHIVE_THRESHOLD`
- `apply_decay()` logs both per-node archive events and a summary decay event
- `unarchive()` restores status to `active` and importance to `IMPORTANCE_DEFAULT` only when the node currently exists and is archived

### 2.2 `feedback.py`

Public exports:

- `upvote(conn, node_id, edge_ids=None)`
- `downvote(conn, node_id)`
- `pin(conn, node_id)`
- `supersede(conn, new_node_id, old_node_id)`

Important current behavior:

- `upvote()` increases node importance and optionally boosts the edges named by `edge_ids` — each a `(source_id, target_id, relation)` tuple — by `EDGE_UPVOTE_DELTA`
- `downvote()` reduces node importance but does not auto-archive the node
- `pin()` sets importance to `IMPORTANCE_MAX`
- `supersede()` only allows node types listed in `SUPERSEDE_TYPES`, which is currently `{note, entity}`. The actual edge-write and node-state mutation are delegated to `pam.relations.apply_supersedes()` (see 2.3) so the same semantics apply whether the supersession comes from a user command or an ingest-time cue
- all feedback operations append JSONL log entries

### 2.3 `relations.py`

Public exports:

- `apply_supersedes(conn, *, new_node_id, old_node, fact, source)`

Centralized side-effect logic for `SUPERSEDES`. Used by both `pam.feedback.supersede()` (with `source="user"`) and `pam.ingestion.pipeline._infer_explicit_cross_memory_relations` (with `source="ingest_cue"`). Behavior:

- Always creates the edge (or no-op on duplicate by primary key).
- Always sets `old_node.status = "reference"` — idempotent at the status level.
- Dampens `old_node.importance` by `SUPERSEDE_IMPORTANCE_FACTOR` only on first creation, so replay does not multiply the dampening.
- Always logs a `supersede` lifecycle event with `source` ∈ {"user", "ingest_cue"} and `edge_created` distinguishing first vs replay.

This module exists to keep the supersession contract single-sourced — closes audit O3.

---

## 3. Current Data And Status Semantics

Lifecycle still revolves around the same importance field, but the live rules are:

- new nodes generally start at `IMPORTANCE_DEFAULT`
- pinned nodes are represented by `importance == IMPORTANCE_MAX`
- archived nodes are hidden by status, not by deleting them
- superseded nodes are represented as `status="reference"` plus a `SUPERSEDES` edge from the newer node

Status transitions controlled here:

- `active -> archived` through decay
- `draft -> archived` through decay
- `reference -> archived` through decay
- `archived -> active` through `unarchive()`
- `active|draft|reference -> reference` through `supersede()` on the older node

This is already a useful baseline for memory evolution. It gives PAM a way to say "this thought was replaced" instead of just overwriting history.

---

## 4. Why Lifecycle Matters More In A Personal Memory System

In a personal-memory system, lifecycle is not just cleanup. It shapes what the agent thinks is current, historical, central, or obsolete.

That means lifecycle policy should support all of the following simultaneously:

- preserve the current best version of a thought
- retain enough old context to answer historical and evolution questions
- avoid letting stale low-signal notes dominate retrieval
- keep corrections and replacements visible as graph structure, not only as changed importance

The existing `SUPERSEDES` and `reference` behavior is the strongest example of this philosophy already present in the code.

---

## 5. Logging And Timestamps

Both files append JSONL records to `LOG_PATH`.

That matters because lifecycle and feedback also affect future decay indirectly:

- `update_importance()` refreshes `updated_at`
- `update_node(..., status=...)` refreshes `updated_at`

So an upvote, pin, downvote, supersede, archive, or unarchive changes the timestamp used by later decay passes.

This is reasonable for the current model, but future graph-native ranking may want to distinguish:

- when a memory was last edited or maintained
- when it was originally valid
- when it became superseded

---

## 6. Future Work For Graph-Native Memory Maintenance

The docs should be explicit about the next lifecycle questions.

### 6.1 Better evolution-chain handling

Supersession today is pairwise. Over time PAM may need to reason over longer chains of revisions or corrected beliefs.

### 6.2 More intentional handling of `reference` nodes

`reference` is already useful because it lets retrieval surface historical context without treating it as fully current. The retrieval layer should use that status more deliberately on change-oriented queries.

### 6.3 Feedback on links, not only nodes

The personal-memory graph will eventually need stronger ways to reinforce or reject specific relationships when the user knows the graph is wrong or incomplete.

### 6.4 Dependable history without clutter

Lifecycle should help PAM keep old material available for evolution and provenance questions without letting old clutter overwhelm current work.

---

## 7. Invariants To Preserve

- pinned nodes must remain decay-immune
- decay decisions must be based on `updated_at`
- `supersede()` must not repeatedly halve importance on duplicate calls
- downvotes should stay local to the node and not mutate edges
- `SUPERSEDES` is currently restricted to `note` and `entity` nodes
- any future graph-maintenance feature should preserve explainable history rather than replacing it with opaque scores alone
