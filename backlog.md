# Backlog

Open work that doesn't belong in the dated audit/test_findings, isn't on a current sprint, but shouldn't get lost. Each item should be specific enough to act on cold.

When an item gets picked up, move it into a session doc or `audits/` / `test_findings/` and remove it from here.

---

## Eval / quality

### F3 — post-supersession answer prompt [next] <!-- from: docs/AUDIT_2026-05-06.md -->
**Why:** detailed Q55 (`"What launch correction superseded the April 18 plan?"`) returns NO_ANSWER. Retrieval surfaces the new node with the SUPERSEDES path, but Claude refuses because the new note title (`"Idea: revise X to Y…"`) reads as tentative under the "if not supported reply NO_ANSWER" rule.
**How to apply:** either (a) add a prompt rule that an outgoing SUPERSEDES edge promotes a tentative-sounding note to a current value, or (b) add a `## Current values` section in `format_for_context_window` that flattens SUPERSEDES paths.

### Detailed-suite residual miss triage <!-- from: test_findings/2026-05-08_17-37-11_eval-full-pass.md -->
**Why:** today's full run shifted detailed to 96/110 (rel 22/26, paraphrase 23/28). ~14 residual misses remain — most likely matcher false-negatives but unclassified. As of the 2026-05-09 Phase A.1 run the detailed number is 93/110 with 3 new misses (idx 43, 81, 94) that look like matcher-FNs in description form — those triage cleanly with the same triage pass.
**How to apply:** triage residual misses (classify into matcher-FN / retrieval-gap / answer-prompt). Per the matcher-as-triage-filter decision, surface real misses for action and discard matcher-FNs. Lower priority than the F3 + hybrid-retrieval items above given today's lift.

---

## Architecture / roadmap

### Hybrid retrieval: FTS + embeddings + write-time cue rules [shipped: A.2 closed via three structural commits 2026-05-12] <!-- from: docs/BACKLOG.md -->
**Why:** Phase A.1 (shipped 2026-05-09, `052b0ef`) added a BGE vector channel and fixed colloquial-relationship 6/16 → 13/16. Phase A.2 attempted 4 rank-key cells + 3 ablation branches on 2026-05-11–12 — all rejected (either regressed IRL colloquial / Hard, or didn't reach idx 81/86/87). Meta-finding from the ablation: the relationship-mode assembly path bypasses `node_scores`, and idx 81's gold has zero FTS/vec signal at all (reaches the pool only via DERIVED_FROM from a seed).

**Resolution (2026-05-12 evening session):** the diagnostic gap (`score_components` empty in CLI JSON) blocked both Position A and Position B from making non-conjectural predictions. Once surfaced, the data showed two distinct failure modes that the prior ablations had conflated, and pointed at three surgical commits — none requiring typed-edge ingestion or schema changes:

| commit | change | targets fixed |
|---|---|---|
| `91b1b98` | `_support_path_result_nodes` sorts by `node_scores` + path-endpoint bonus (`RELATIONSHIP_PRIORITY_BONUS=0.1`) | idx 86, 87 (rank 11 → 1) |
| `a8a5592` | DERIVED_FROM score propagation when seed text ≥ 0.15 and target text ≤ 0.05 (α=0.5) | idx 81 (rank 11 → 8 in ordered_nodes) |
| `243c3ea` | `_rank_relationship_hits` no longer drops non-directional edges when any directional match exists | idx 81 end-to-end (seed→gold edge now surfaces in `result.relationships` for Claude) |

**Claude eval validation (detailed-relationship idx 81–87): 7/7 PASS.** Python eval detailed 104/110, IRL 59/68 with colloquial 13/16 held. Hard idx 1-32 Claude eval: 32/32 (lookup 12, paraphrase 6, relationship 6, timeline 4, negative 4). 201 unit tests pass. Hard idx 33-96 spot-check in progress.

**Remaining follow-ups:**
1. **Delete A.2 ablation branches** (`a2-mmr`, `a2-contrast`, `a2-mode-switch`) — findings absorbed into commit messages.
2. Full detailed/IRL/Large Claude eval pass on the shipped config — single Claude-rate-window job, not blocking.
3. Backfill script `pam migrate --backfill-embeddings` for existing DBs (currently only post-v2 ingests get embedded).
4. Entity-record embeddings (deferred from A.1).
5. F3 (post-supersession answer prompt) — still parked. idx 81 is no longer the canonical case; F3 is now its own thing for SUPERSEDES-driven tentative-language refusals.

### True multi-hop graph traversal *(O7c)* <!-- from: docs/BACKLOG.md -->
**Why:** `pam/retrieval/graph_expander.py:258` carries a TODO for constrained multi-hop with path provenance. Today's expander does a fixed traversal pattern. Roadmap-level. Today's eval does not yet present a failing query that obviously requires multi-hop — see decision 2026-05-07 for the deferral reasoning. Stays parked behind the colloquial-relationship suite producing harder cases.

---

## Code housekeeping (low-priority)

### Confirm answer-side default model <!-- from: ~/.claude/sessions/PAM/2026-05-07.md -->
**Why:** `CHAT_ANSWER_MODEL` defaults to `claude-sonnet-4.5` in `config.py`. Alternatives the user named: `claude-opus-4`, `gpt-5`. Worth a one-shot eval comparison before changing.

### Full-suite end-to-end nightly <!-- from: ~/.claude/sessions/PAM/2026-05-07.md -->
**Why:** the 2026-05-07 full run took ~2h wall-clock and ate one Claude rate-limit window. Nightly cron via the harness's `--start-from` would amortize that. Lower priority than the items above; only worth setting up if the full-suite number becomes a published metric.
