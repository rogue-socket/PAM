# Backlog

Open work that doesn't belong in the dated audit/test_findings, isn't on a current sprint, but shouldn't get lost. Each item should be specific enough to act on cold.

When an item gets picked up, move it into a session doc or `audits/` / `test_findings/` and remove it from here.

---

## Architecture / roadmap

### Backfill embeddings on existing DBs [next] <!-- from: A.1 / A.2 follow-up -->
**Why:** Phase A.1 added BGE vector channel; only post-migration-v2 ingests get embedded. Existing repo `pam.db` content has no embedding until each node is edited.
**How to apply:** `pam migrate --backfill-embeddings` CLI command that walks all nodes missing embeddings and runs them through the encoder. Idempotent.

### Entity-record embeddings [next] <!-- from: A.1 follow-up -->
**Why:** Today only event/note/source nodes are embedded. Entity records (people, projects, places) aren't, so colloquial queries that name an entity by role don't get an entity-direct vector hit.
**How to apply:** add embeddings to entity-type nodes at ingest + backfill.

### True multi-hop graph traversal *(O7c)* <!-- from: docs/BACKLOG.md -->
**Why:** `pam/retrieval/graph_expander.py:258` carries a TODO for constrained multi-hop with path provenance. Today's expander does a fixed traversal pattern. Roadmap-level. Today's eval does not yet present a failing query that obviously requires multi-hop — see decision 2026-05-07 for the deferral reasoning. Stays parked behind the colloquial-relationship suite producing harder cases.

---

## Code housekeeping (low-priority)

### Confirm answer-side default model <!-- from: ~/.claude/sessions/PAM/2026-05-07.md -->
**Why:** `CHAT_ANSWER_MODEL` defaults to `claude-sonnet-4.5` in `config.py`. Alternatives the user named: `claude-opus-4`, `gpt-5`. Worth a one-shot eval comparison before changing.

### Full-suite end-to-end nightly <!-- from: ~/.claude/sessions/PAM/2026-05-07.md -->
**Why:** the 2026-05-07 full run took ~2h wall-clock and ate one Claude rate-limit window. Nightly cron via the harness's `--start-from` would amortize that. Lower priority than the items above; only worth setting up if the full-suite number becomes a published metric.
