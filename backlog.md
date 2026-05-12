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

### Hybrid retrieval: FTS + embeddings + write-time cue rules [active: A.2 unresolved, w_recency sweep next] <!-- from: docs/BACKLOG.md -->
**Why:** today's retrieval is FTS5 + BGE vector. The colloquial-relationship row is fixed (Phase A.1). The detailed-relationship row is still −2 below the 96 floor, and the diagnosis is that high-recency vector-pollution outranks older textually-relevant gold notes within top-10.

**Status:** Phase A.1 landed 2026-05-09 (`colloquial_relationship` 6/16 → 13/16; detailed 96 → 93 raw). Phase A.2 attempted 2026-05-11–12 in two waves:

1. **Floor sweep (cell `VEC_SIMILARITY_FLOOR=0.60`)** — detailed 93 → 99 (good) but IRL colloquial 13/16 → 6/16 (catastrophic; rejected).
2. **`TOP_K=10 → 15`** — detailed +5, IRL +3 (colloquial +1), but **Hard 192/192 → 148/192 (−44 NO_ANSWER refusals)**. Net across suites: −36. Reverted in `config.py:9`. The diagnostic via `cli.py query --json --top 20` was correct (gold notes live at rank 11+ at TOP_K=10), but lifting them via pool size is the wrong lever because Hard breaks. See [`test_findings/2026-05-11_19-42-34_a2-topk-bump.md`](test_findings/2026-05-11_19-42-34_a2-topk-bump.md).

**Next attempt — w_recency sweep:**
- Lower `WEIGHT_RECENCY` from 0.30 → 0.20 at `TOP_K=10` to address the diagnosed pollution-by-recency directly within rank. Hypothesis: gold notes for detailed misses are older within their corpus; recency weight is pushing them down. Reducing the weight lifts them without growing the context window, so Hard's literal-anchor lookups stay clean.
- Add `PAM_W_RECENCY` env override to `config.py` first.
- Run detailed + IRL + Hard + Large (one cell, full guardrail). If Hard holds at 192/192 and detailed ≥96, ship. If Hard regresses, A.2 ends here.

**Other follow-ups (lower priority):**
1. Triage detailed idx 56 / 63 / 67 (TOP_K=15 new regressions). Likely 1 matcher-FN, 2 real Claude-discrimination losses. Useful baseline reference.
2. idx 86 NO_ANSWER at TOP_K=15 — gold in candidate pool, Claude refused. F3-adjacent prompt-conservatism issue.
3. `score_components` empty in CLI `--json` output — diagnostics blind spot. `format_result_json` doesn't surface the post-weight breakdown the ranker computes.
4. Backfill script `pam migrate --backfill-embeddings` for existing DBs (currently only post-v2 ingests get embedded).
5. Entity-record embeddings (deferred from A.1 per the test_findings entry).

**Phase B (LLM-at-ingest typed edges)** stays parked behind A.2. If the w_recency cell also fails, the right next move may be Phase B rather than further A.2 tuning — the residual misses (rank-blocked gold) are exactly what typed edges would fix structurally.

**Guardrail bookkeeping:** detailed ≥96/110 still violated at the shipped config (`TOP_K=10`, floor=0.50, w_recency=0.30). −2 raw / ~−2 real.

### True multi-hop graph traversal *(O7c)* <!-- from: docs/BACKLOG.md -->
**Why:** `pam/retrieval/graph_expander.py:258` carries a TODO for constrained multi-hop with path provenance. Today's expander does a fixed traversal pattern. Roadmap-level. Today's eval does not yet present a failing query that obviously requires multi-hop — see decision 2026-05-07 for the deferral reasoning. Stays parked behind the colloquial-relationship suite producing harder cases.

---

## Code housekeeping (low-priority)

### Confirm answer-side default model <!-- from: ~/.claude/sessions/PAM/2026-05-07.md -->
**Why:** `CHAT_ANSWER_MODEL` defaults to `claude-sonnet-4.5` in `config.py`. Alternatives the user named: `claude-opus-4`, `gpt-5`. Worth a one-shot eval comparison before changing.

### Full-suite end-to-end nightly <!-- from: ~/.claude/sessions/PAM/2026-05-07.md -->
**Why:** the 2026-05-07 full run took ~2h wall-clock and ate one Claude rate-limit window. Nightly cron via the harness's `--start-from` would amortize that. Lower priority than the items above; only worth setting up if the full-suite number becomes a published metric.
