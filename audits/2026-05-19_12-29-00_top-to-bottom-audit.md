# Audit — 2026-05-19 (top-to-bottom)

Comprehensive product audit triggered by `/goal audit the entire product, top to bottom, right to left, nothing should be left`. Four parallel subagent passes (write path, read path, surface layer, tests+scripts+docs) followed by manual verification of every claim before recording here. Findings the subagents made that did not survive verification are listed at the bottom with the reason for the push-back.

State at audit time: `main` at `293ad02`, working tree clean, 222 unit tests green (per handoffs/2026-05-19.md).

---

## Highest-impact (fix today)

### 1. `pam/retrieval/search.py:129-133` — dead `if/pass` guard in `_time_range_seed_candidates`

```python
if parsed.intent != "timeline" and not parsed.keywords:
    # Avoid hijacking lookup queries that happen to mention a date.
    # Fire only when intent is explicitly timeline OR there are no keywords
    # at all (every other path has already failed).
    pass
```

The block exists to gate the time-range fallback — per the comment, lookup queries that *happen to mention a date* should not be hijacked into a date-range scan. The action is `pass`, so the guard is a no-op and the function always proceeds to build the SQL clause. Either an early `return []` was lost in a refactor, or the condition is inverted (the comment's "fire when" is the opposite of the current `if`).

**Impact bounded** — this is the last-resort fallback in `fts_search_with_filter` (line 217), only reached after FTS, anchor seed, and FTS retry have all returned empty. But the intent is broken and the dead block is misleading.

**Fix:** either restore the early-return so the function only fires under the documented condition, or remove the block entirely if the current behavior (always fire) is intended. Add a test in `tests/test_retrieval.py` covering a non-timeline lookup query that has a date mention plus keywords that miss FTS.

### 2. `OPENAI_MODEL` env-default mismatch across modules

- `pam/ingestion/llm.py:88` — `os.getenv("OPENAI_MODEL", "gpt-4o-mini")`
- `pam/retrieval/query_parser.py:520` — `os.getenv("OPENAI_MODEL", "gpt-4.1-mini")`

The same env var resolves to two different models depending on whether OpenAI is being used for ingestion-time helpers vs. query parsing. Both model IDs are valid (the surface-audit subagent claimed `gpt-4.1-mini` doesn't exist — that was wrong, it's a real model), so this is not a "broken" path, but the inconsistency is invisible silent drift.

**Fix:** add `LLM_OPENAI_MODEL` to `config.py`, default it from `os.getenv("OPENAI_MODEL", "gpt-4o-mini")` in one place, import from both sites.

---

## Small cleanups (one-commit batch)

### 3. Unused `import json` in two modules

- `pam/feedback.py:3` — zero `json.` references in file.
- `pam/lifecycle.py:3` — zero `json.` references in file.

**Fix:** remove both lines.

### 4. `pam/lifecycle.py:102-108` — `unarchive()` missing telemetry log entry

Every other state-mutating op in `feedback.py`, `lifecycle.py`, `relations.py` emits an `_append_log({"event": …, ...})` line. `unarchive` calls `update_node(conn, node_id, status="active", importance=IMPORTANCE_DEFAULT)` and returns. No log line. Asymmetric audit trail.

**Fix:** add an `_append_log({"event": "unarchive", "node_id": node_id, "restored_importance": IMPORTANCE_DEFAULT})` call after the update.

### 5. `pam/feedback.py:31-32` — `_get_feedback_node` is useless indirection — **consider**

One-line wrapper around `get_node(conn, node_id)`, 4 in-file callers (lines 61, 85, 101, 116-117). No behavior added. Either inline it or drop it. Cosmetic only.

---

## Documentation drift (doc-only)

### 6. CLAUDE.md "Retrieval result contract" understates `score_components`

CLAUDE.md says `score_components[node_id]` carries "the post-weight `{text_relevance, recency, importance, entity_bonus}` breakdown — the four entries sum exactly to the rank-key."

Reality:
- `pam/retrieval/ranker.py:90-96` emits **five** entries — includes `vector_similarity` (hybrid retrieval path added it).
- `pam/retrieval/ranker.py:636-658` (`_propagate_along_derived_from`) adds a sixth `derived_propagation` key when a `DERIVED_FROM` edge propagates score from an FTS-anchored seed to a near-zero-text-relevance target.

The invariant (components sum to total) is still upheld — verified at `ranker.py:97-103` and at the `setdefault` arithmetic in lines 654-658, which adds the boost to both `node_scores` and `score_components[target_id]["derived_propagation"]` in lockstep.

**Fix:** update CLAUDE.md to list five baseline entries (add `vector_similarity`) and note the optional `derived_propagation` entry that appears when the propagation path fires. Keep the "sum to rank-key" wording — that's the actual invariant and it still holds.

---

## Consider (low impact at current scale)

### 7. `pam/lifecycle.py:38` — `_eligible_nodes` loads all nodes into memory

```python
return [node for node in list_nodes(conn, limit=None) if node.status in ELIGIBLE_STATUSES]
```

Filters in Python after pulling every row. Fine for a personal-memory store; would matter at 100k+ nodes. If it becomes a problem, push the status filter into SQL by extending `list_nodes()` to accept a multi-status filter, or write a direct query in `lifecycle.py`.

### 8. CLI-level test gaps in `tests/test_cli.py`

Module-level behavior IS tested (`test_lifecycle.py`, `test_feedback*`, `test_doctor.py`) — but the Click invocation layer is not covered for: `list_cmd` filters (`--type`, `--status`), `upvote_cmd`, `downvote_cmd`, `pin_cmd`, `supersede_cmd`, `unarchive_cmd`, `decay`, `rebuild_fts_cmd`. Low priority — these are thin Click wrappers around tested functions — but worth one batch of `CliRunner.invoke` tests if a regression slips through.

### 9. `pam/retrieval/graph_expander.py:278-359` — repeated `get_node()` in hot loops

Already noted in the prior session. Pairs naturally with the multi-hop backlog item — when expansion gets reworked, batching falls out. Not worth touching as a standalone perf fix.

---

## Subagent claims that did NOT survive verification (recorded so they don't get re-flagged)

### Pushed back: "Weights sum to 1.10, violates rank-key contract"

`WEIGHT_TEXT_RELEVANCE + WEIGHT_VEC_SIMILARITY + WEIGHT_RECENCY + WEIGHT_IMPORTANCE = 0.30 + 0.25 + 0.30 + 0.25 = 1.10`. Mathematically true but not a contract violation. The contract is *components sum to total*, not *weights sum to 1.0*. Code at `ranker.py:97-103` upholds the real contract. Magnitudes not normalized to [0,1] is not an invariant anywhere in the codebase.

### Pushed back: "`gpt-4.1-mini` is an invalid model ID"

It's a real OpenAI model. The inconsistency *between* the two defaults (item 2 above) is the real finding; the model ID itself is fine.

### Pushed back: "schema.py:251 `DEFAULT ''` for workspace_id is a footgun"

Standard SQLite migration idiom for `ALTER TABLE … ADD COLUMN NOT NULL`. The very next block (lines 254-262) backfills the empty strings with `resolve_workspace_id()`. New nodes never see the default — `add_node()` sets `workspace_id` explicitly. Not a bug.

### Pushed back: "downvote/pin need transaction() wrappers like upvote does"

Both do single auto-commit writes via `update_importance()`. The real concern (telemetry append outside the txn means partial-failure desync) is already on `backlog.md` as the "Telemetry-in-txn (Phase 1 closure)" item.

### Pushed back: "Draft entities leak via graph_expander support paths"

Subagent didn't pin a concrete leak. `_is_surfaceable` filters drafts from direct results per the architecture invariant; support-path objects carry node IDs but the consumer (`ranker.py`) filters drafts before assembling `RetrievalResult` buckets. No verified leak path.

---

## Already on backlog (not re-flagging)

- Eval transcript text preservation
- Telemetry-in-txn (Phase 1 closure)
- True multi-hop graph traversal (O7c)
- Graph-quality diagnostics + miss categorization
- Confirm answer-side default model
- Nightly full-suite cron

---

## Severity summary

| Severity | Count | Items |
|----------|-------|-------|
| Fix | 5 | dead guard in search.py; OPENAI_MODEL drift; 2× unused json import; unarchive missing log |
| Fix (doc-only) | 1 | CLAUDE.md score_components count |
| Consider | 4 | feedback wrapper indirection; unbounded list_nodes at decay; CLI-level test gaps; graph_expander N+1 |
| Pushed back | 5 | weight-sum, model-ID, workspace-default, downvote-txn, draft-leak |

No correctness bugs that break the write contract. No invariant violations in the read path (verified). Substrate is healthy; everything actionable here is small.

## Suggested follow-up

One commit covering items 1–4 plus the CLAUDE.md doc fix (item 6). Items 5 and 7-9 are optional and can wait. The pushed-back items are recorded here so future audits don't burn cycles re-investigating them.
