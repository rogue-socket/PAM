# Backlog

Open work that doesn't belong in the dated audit/test_findings, isn't on a current sprint, but shouldn't get lost. Each item should be specific enough to act on cold.

When an item gets picked up, move it into a session doc or `audits/` / `test_findings/` and remove it from here.

---

## Eval / quality

### F3 — post-supersession answer prompt <!-- from: docs/AUDIT_2026-05-06.md -->
**Why:** detailed Q55 (`"What launch correction superseded the April 18 plan?"`) returns NO_ANSWER. Retrieval surfaces the new node with the SUPERSEDES path, but Claude refuses because the new note title (`"Idea: revise X to Y…"`) reads as tentative under the "if not supported reply NO_ANSWER" rule.
**How to apply:** either (a) add a prompt rule that an outgoing SUPERSEDES edge promotes a tentative-sounding note to a current value, or (b) add a `## Current values` section in `format_for_context_window` that flattens SUPERSEDES paths.

### Detailed-suite residual miss triage <!-- from: test_findings/2026-05-08_17-37-11_eval-full-pass.md -->
**Why:** today's full run shifted detailed to 96/110 (rel 22/26, paraphrase 23/28). ~14 residual misses remain — most likely matcher false-negatives but unclassified.
**How to apply:** triage residual misses (classify into matcher-FN / retrieval-gap / answer-prompt). Per the matcher-as-triage-filter decision, surface real misses for action and discard matcher-FNs. Lower priority than the F3 + hybrid-retrieval items above given today's lift.

---

## Architecture / roadmap

### Hybrid retrieval: FTS + embeddings + write-time cue rules <!-- from: docs/BACKLOG.md -->
**Why:** today's retrieval is FTS5 only. That's why Q24 fails — the answer note has zero token overlap with the question. Two complementary directions:

1. **Embeddings (vector search)** as a second recall channel. Encode each node's content + summary + linked entity names; encode the query the same way; surface top-k by cosine similarity alongside FTS hits. Catches semantic paraphrase like `"1:1 with Anya"` ≈ `"who's my manager"`.
2. **Write-time cue rules for relationship inference.** When ingest sees `"1:1 with X"`, `"X reviewed my PR"`, etc., write a typed edge (`MANAGES`, `REVIEWED`, `COLLABORATES_WITH`) with a `confidence` field. Then graph queries can answer role questions without semantic retrieval.

These aren't either-or. Embeddings give recall on phrasing variation; cue rules give precision on high-confidence patterns and let the graph stay queryable.

**What this needs before code:**
- A short design doc (`prds/<date>_retrieval-hybrid-plan.md` or extend `docs/RETRIEVAL_RELATIONS_PLAN.md`) covering: embedding model + dimensions + storage (sqlite-vec? sqlite-vss? a sidecar?), how vector and FTS scores combine in the ranker, what cue patterns we trust enough to write edges from, how cue confidence flows into edge weight, and how the deterministic fallback contract holds when the embedding model is unavailable.
- A measurable evaluation gate — the `colloquial_relationship` row in the IRL eval (5 queries, **0/5 confirmed on 2026-05-08 full run**) is the natural target.

**Definition of done (planning step, not the build):** a design doc the team can argue with. Build is downstream of agreement.

### True multi-hop graph traversal *(O7c)* <!-- from: docs/BACKLOG.md -->
**Why:** `pam/retrieval/graph_expander.py:258` carries a TODO for constrained multi-hop with path provenance. Today's expander does a fixed traversal pattern. Roadmap-level. Today's eval does not yet present a failing query that obviously requires multi-hop — see decision 2026-05-07 for the deferral reasoning. Stays parked behind the colloquial-relationship suite producing harder cases.

---

## Code housekeeping (low-priority)

### Confirm answer-side default model <!-- from: ~/.claude/sessions/PAM/2026-05-07.md -->
**Why:** `CHAT_ANSWER_MODEL` defaults to `claude-sonnet-4.5` in `config.py`. Alternatives the user named: `claude-opus-4`, `gpt-5`. Worth a one-shot eval comparison before changing.

### Full-suite end-to-end nightly <!-- from: ~/.claude/sessions/PAM/2026-05-07.md -->
**Why:** the 2026-05-07 full run took ~2h wall-clock and ate one Claude rate-limit window. Nightly cron via the harness's `--start-from` would amortize that. Lower priority than the items above; only worth setting up if the full-suite number becomes a published metric.
