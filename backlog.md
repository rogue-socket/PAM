# Backlog

Open work that doesn't belong in the dated audit/test_findings, isn't on a current sprint, but shouldn't get lost. Each item should be specific enough to act on cold.

When an item gets picked up, move it into a session doc or `audits/` / `test_findings/` and remove it from here.

---

## Eval / quality

### Eval script preserves Claude's response text [next] <!-- from: handoffs/2026-05-19.md /wrap -->
**Why:** today's detailed-eval per-flip diff (101/110 → 100/110) couldn't be triaged because the saved transcript JSON only stores `{index, query_type, query, answer, passed}` — no actual model output. Per `feedback_prompt_rule_vs_matcher_fn.md`, real eval methodology is per-flip text inspection; raw count alone is misleading. The 3 newly-failing cases (#43 / #63 / #78) are stuck at "unknown — could be matcher-FN, could be pick-variance, could be real" until the next run captures text.
**How to apply:** in `scripts/run_copilot_cli_eval.py` add the Claude response to each transcript entry before serializing. Probably one extra field on the per-query dict. Verify by rerunning detailed and confirming the text shows up under `summary.transcript[i]`.

### Graph-quality diagnostics + miss categorization [next] <!-- from: DEPENDABILITY_PLAN.md Phase 2 -->
**Why:** Phase 2 item 3 from the dependability plan. A bad graph-native answer today reads as a single "miss" with no failure class — could be missing edge, missed expansion, weak ranking, weak rendering, or Claude pick-variance. As PAM moves more graph-native, this opacity is the bigger risk. Pairs naturally with the eval-transcript-preservation item above.
**How to apply:** add a per-miss classifier to the eval harness that checks: (a) does retrieval return the gold node? (b) does graph expansion reach it? (c) does ranking surface it in top-k? (d) does rendering produce the right edge facts? Report per-class counts in the eval summary.

---

## Dependability

### Telemetry-in-txn (Phase 1 closure) [next] <!-- from: handoffs/2026-05-19.md /wrap -->
**Why:** Phase 1 left JSONL appends outside the SQLite transaction by design (per `docs/DEPENDABILITY_PLAN.md`: "telemetry is best-effort, not atomic"). Worth one focused commit to either (a) move appends inside the txn so log can't desync from partial failures, or (b) write a `decisions.md` entry making the best-effort stance durable. Today's plan leans toward (b) — the rationale is in the plan — but the call hasn't been made explicitly yet.
**How to apply:** either thread an `append_log` into the transaction's success path in `relations.py`, `feedback.py`, `lifecycle.py`, OR add a one-paragraph `decisions.md` entry citing the plan and locking in best-effort semantics. Don't do both.

---

## Architecture / roadmap

### True multi-hop graph traversal *(O7c)* <!-- from: docs/BACKLOG.md -->
**Why:** `pam/retrieval/graph_expander.py:258` carries a TODO for constrained multi-hop with path provenance. Today's expander does a fixed traversal pattern. Roadmap-level. Today's eval does not yet present a failing query that obviously requires multi-hop — see decision 2026-05-07 for the deferral reasoning. Stays parked behind the colloquial-relationship suite producing harder cases.

---

## Code housekeeping (low-priority)

### Confirm answer-side default model <!-- from: ~/.claude/sessions/PAM/2026-05-07.md -->
**Why:** `CHAT_ANSWER_MODEL` defaults to `claude-sonnet-4.5` in `config.py`. Alternatives the user named: `claude-opus-4`, `gpt-5`. Worth a one-shot eval comparison before changing.

### Full-suite end-to-end nightly <!-- from: ~/.claude/sessions/PAM/2026-05-07.md -->
**Why:** the 2026-05-07 full run took ~2h wall-clock and ate one Claude rate-limit window. Nightly cron via the harness's `--start-from` would amortize that. Lower priority than the items above; only worth setting up if the full-suite number becomes a published metric.
