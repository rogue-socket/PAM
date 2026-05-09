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

**Status:** Phase A.1 (node embeddings only — entity embeddings + backfill deferred) landed 2026-05-09. Trigger row crushed: `colloquial_relationship` 6/16 → **13/16 (81.3%)** on the expanded IRL gate. Hard 192/192 and large 200/200 held. Detailed 96/110 → 93/110 (-3 raw, ~-1 to -2 after matcher-FN triage). See [`test_findings/2026-05-09_02-02-20_phase-a1-irl-lift.md`](test_findings/2026-05-09_02-02-20_phase-a1-irl-lift.md).

**Next (Phase A.2):**
1. Sweep the four tunable numbers (`w_text=0.30`, `w_vec=0.25`, `VEC_SIMILARITY_FLOOR=0.5`, FTS-50 ∪ vec-50) on the expanded IRL gate plus detailed as a guardrail. Goal: keep IRL ≥56/68 while clawing detailed back to ≥96/110.
2. Triage the 3 detailed relationship misses that look like matcher-FNs (idx 43, 81, 94 in the 2026-05-09 run) — Claude-confirmation pass to nail down the real regression number.
3. Backfill script `pam migrate --backfill-embeddings` for existing DBs (currently only post-v2 ingests get embedded).
4. Entity-record embeddings (deferred from A.1 per the test_findings entry).

**Phase B (LLM-at-ingest typed edges)** stays parked behind A.2. Three IRL colloquial misses (`"who do I pair with on code?"`, `"who's my most frequent collaborator?"`, `"who critiques my code?"`) suggest typed `COLLABORATES_WITH`/`REVIEWS` edges would help — but A.2 weight-sweep may close enough of the gap that B isn't needed. Don't start B before A.2 numbers land.

**Guardrail bookkeeping:** the design doc's strict reading of the floor (detailed ≥96/110) is currently violated by 3 raw / ~1-2 real hits. A.2 must restore it.

### True multi-hop graph traversal *(O7c)* <!-- from: docs/BACKLOG.md -->
**Why:** `pam/retrieval/graph_expander.py:258` carries a TODO for constrained multi-hop with path provenance. Today's expander does a fixed traversal pattern. Roadmap-level. Today's eval does not yet present a failing query that obviously requires multi-hop — see decision 2026-05-07 for the deferral reasoning. Stays parked behind the colloquial-relationship suite producing harder cases.

---

## Code housekeeping (low-priority)

### Confirm answer-side default model <!-- from: ~/.claude/sessions/PAM/2026-05-07.md -->
**Why:** `CHAT_ANSWER_MODEL` defaults to `claude-sonnet-4.5` in `config.py`. Alternatives the user named: `claude-opus-4`, `gpt-5`. Worth a one-shot eval comparison before changing.

### Full-suite end-to-end nightly <!-- from: ~/.claude/sessions/PAM/2026-05-07.md -->
**Why:** the 2026-05-07 full run took ~2h wall-clock and ate one Claude rate-limit window. Nightly cron via the harness's `--start-from` would amortize that. Lower priority than the items above; only worth setting up if the full-suite number becomes a published metric.
