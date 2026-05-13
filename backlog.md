# Backlog

Open work that doesn't belong in the dated audit/test_findings, isn't on a current sprint, but shouldn't get lost. Each item should be specific enough to act on cold.

When an item gets picked up, move it into a session doc or `audits/` / `test_findings/` and remove it from here.

---

## Eval / quality

### F3 — post-supersession answer prompt [next] <!-- from: docs/AUDIT_2026-05-06.md -->
**Why:** detailed Q55 (`"What launch correction superseded the April 18 plan?"`) returns NO_ANSWER. Retrieval surfaces the new node with the SUPERSEDES path, but Claude refuses because the new note title (`"Idea: revise X to Y…"`) reads as tentative under the "if not supported reply NO_ANSWER" rule.
**How to apply:** either (a) add a prompt rule that an outgoing SUPERSEDES edge promotes a tentative-sounding note to a current value, or (b) add a `## Current values` section in `format_for_context_window` that flattens SUPERSEDES paths.

### Detailed-suite residual miss triage [next] <!-- from: test_findings/2026-05-12_22-30-00_a2-close.md -->
**Why:** A.2 closed at 96/110 raw (+3 vs A.1 baseline). Remaining 14 misses include known matcher-FNs (#87 "Parser fallback guide", #94 "Acoustic experiment log"), one Claude TIMEOUT (#28), and Claude-pick-variance cases (#81 when storm-handwriting wins). Classify into matcher-FN / Claude-noise / retrieval-gap before deciding if any need code.
**How to apply:** triage pass against the 14 misses; matcher-FN absorption could push the real number to ~99/110.

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
