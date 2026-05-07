# Backlog

Open work that doesn't belong in the dated audit/test_findings, isn't on a current sprint, but shouldn't get lost. Each item should be specific enough to act on cold.

When an item gets picked up, move it into a session doc or `audits/` / `test_findings/` and remove it from here.

---

## Eval / quality

### Expand the colloquial-relationship test corpus <!-- from: docs/BACKLOG.md -->
**Why:** Q24 (`"who do I report to?"`) is the canonical example of a query class that the FTS-led baseline cannot answer — because the corpus uses *colloquial language* for the relationship (`"1:1 with Anya"`) instead of the keyword the user types (`"manager"`, `"report to"`). One example doesn't make a measurable suite. Before investing in semantic retrieval or write-time relation inference, we want enough Q24-shaped queries that we can measure whether a fix actually moves the number.

**Suggested additions to `tests/fixtures/irl_eval_corpus.json`:**
- `"1:1 with X"` → `"who's my manager?"` / `"who do I report to?"` / `"who's my skip-level?"`
- `"coffee chat with X"` / `"grabbed lunch with X"` → `"do I know X well?"`
- `"X assigned me to Y"` / `"X asked me to do Y"` → `"who's running Y?"` / `"what's my main project?"`
- `"shipped Y for X's team"` → `"what team am I on?"`
- `"X reviewed my PR"` → `"who reviews my code?"`

**Definition of done:** at least 5 colloquial-relationship queries in the IRL fixture, with corresponding corpus items that contain the relationship indirectly. Each should fail today's FTS baseline (zero retrieval recall) so the eval clearly distinguishes baseline from any future fix.

### Q21 first-person framing in the answer prompt <!-- from: ~/.claude/sessions/PAM/2026-05-07.md -->
**Why:** IRL miss `"what did I do last week?"` returns NO_ANSWER because Claude reads notes like `"Diego shadowed me debugging…"` as third-person. Retrieval is correct; this is an answer-prompt issue. Single-rule ablation.
**How to apply:** add one prompt rule recognising first-person reflexive queries (`"what did I/we do…"`); test against IRL Q21 and the broader IRL set to verify no regression. Yesterday's lesson: prompt rules don't compose monotonically — verify with the full IRL suite, not just the target query.

### F3 — post-supersession answer prompt <!-- from: docs/AUDIT_2026-05-06.md -->
**Why:** detailed Q55 (`"What launch correction superseded the April 18 plan?"`) returns NO_ANSWER. Retrieval surfaces the new node with the SUPERSEDES path, but Claude refuses because the new note title (`"Idea: revise X to Y…"`) reads as tentative under the "if not supported reply NO_ANSWER" rule.
**How to apply:** either (a) add a prompt rule that an outgoing SUPERSEDES edge promotes a tentative-sounding note to a current value, or (b) add a `## Current values` section in `format_for_context_window` that flattens SUPERSEDES paths.

### Detailed-suite paraphrase/relationship tail diagnosis <!-- from: test_findings/2026-05-07_17-30-56_eval-results.md -->
**Why:** detailed eval scored relationship 19/26 and paraphrase 22/28 on the 2026-05-07 full run. ~5 of the 10 misses look like matcher false-negatives; the rest are unclassified.
**How to apply:** triage the 10 misses (classify into matcher-FN / retrieval-gap / answer-prompt). Per the matcher-as-triage-filter decision, surface real misses for action and discard matcher-FNs.

---

## Architecture / roadmap

### Hybrid retrieval: FTS + embeddings + write-time cue rules <!-- from: docs/BACKLOG.md -->
**Why:** today's retrieval is FTS5 only. That's why Q24 fails — the answer note has zero token overlap with the question. Two complementary directions:

1. **Embeddings (vector search)** as a second recall channel. Encode each node's content + summary + linked entity names; encode the query the same way; surface top-k by cosine similarity alongside FTS hits. Catches semantic paraphrase like `"1:1 with Anya"` ≈ `"who's my manager"`.
2. **Write-time cue rules for relationship inference.** When ingest sees `"1:1 with X"`, `"X reviewed my PR"`, etc., write a typed edge (`MANAGES`, `REVIEWED`, `COLLABORATES_WITH`) with a `confidence` field. Then graph queries can answer role questions without semantic retrieval.

These aren't either-or. Embeddings give recall on phrasing variation; cue rules give precision on high-confidence patterns and let the graph stay queryable.

**What this needs before code:**
- A short design doc (`prds/<date>_retrieval-hybrid-plan.md` or extend `docs/RETRIEVAL_RELATIONS_PLAN.md`) covering: embedding model + dimensions + storage (sqlite-vec? sqlite-vss? a sidecar?), how vector and FTS scores combine in the ranker, what cue patterns we trust enough to write edges from, how cue confidence flows into edge weight, and how the deterministic fallback contract holds when the embedding model is unavailable.
- A measurable evaluation gate — the colloquial-relationship suite above is the natural baseline.

**Definition of done (planning step, not the build):** a design doc the team can argue with. Build is downstream of agreement.

### True multi-hop graph traversal *(O7c)* <!-- from: docs/BACKLOG.md -->
**Why:** `pam/retrieval/graph_expander.py:258` carries a TODO for constrained multi-hop with path provenance. Today's expander does a fixed traversal pattern. Roadmap-level. Today's eval does not yet present a failing query that obviously requires multi-hop — see decision 2026-05-07 for the deferral reasoning. Stays parked behind the colloquial-relationship suite producing harder cases.

---

## Code housekeeping (low-priority)

### Confirm answer-side default model <!-- from: ~/.claude/sessions/PAM/2026-05-07.md -->
**Why:** `CHAT_ANSWER_MODEL` defaults to `claude-sonnet-4.5` in `config.py`. Alternatives the user named: `claude-opus-4`, `gpt-5`. Worth a one-shot eval comparison before changing.

### Full-suite end-to-end nightly <!-- from: ~/.claude/sessions/PAM/2026-05-07.md -->
**Why:** the 2026-05-07 full run took ~2h wall-clock and ate one Claude rate-limit window. Nightly cron via the harness's `--start-from` would amortize that. Lower priority than the items above; only worth setting up if the full-suite number becomes a published metric.
