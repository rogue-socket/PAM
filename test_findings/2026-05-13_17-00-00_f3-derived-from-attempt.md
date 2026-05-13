# F3 DERIVED_FROM attempt — reverted (2026-05-13)

Attempt to fix detailed #79 (`"What document grew out of the revised Cedar preference?"` → expected `ocr vendor review`) by adding a directional-edge prompt rule and resolving relationship endpoints to titles in the eval renderer. Outcome: title-resolution kept, prompt rule reverted, real Claude score unchanged.

## What was tried

Two changes to `scripts/run_copilot_cli_eval.py` (eval-side only):

1. **Renderer (`_render_retrieval_context`):** replaced raw UUIDs in the `Relationships:` block with node titles, matching what `pam.agent_interface::_plan_relationships` already does for the agent-facing path.
2. **Prompt (`_prompt_for_answer`):** added a directional-edge rule explaining that `A DERIVED_FROM B` means B grew out of A, `A SUPERSEDES B` means A replaces B, plus the instruction to "treat B/A as a concrete artifact even if its title sounds like a draft."

## What ran

Detailed Claude eval (vectors-on, freshly re-ingested DB):

- Run 3 (`test_findings/eval_runs/2026-05-13_10-07-02_detailed_claude.json`) — full 110 with rate-limit cliff at #78; queries 1-77 clean.
- Run 4 (`test_findings/eval_runs/2026-05-13_11-16-26_detailed_claude.json`) — re-ran 79-110 after rate-limit reset.
- Baseline: `test_findings/eval_runs/2026-05-13_08-58-57_detailed_claude.json` (vectors-on, 97/110).

Combined: 96/109 valid post-fix (one query — #78 — rate-limited in both passes and not re-run).

## 11-flip diff vs vectors-on baseline

| # | Type | Baseline → Post-fix | Verdict |
|---|------|---------------------|---------|
| 6 | lookup | PASS → FAIL | matcher-FN flip; Claude said `5` instead of `5 keywords` |
| 22 | lookup | FAIL → PASS | matcher-FN absorption (Claude phrasing varied) |
| 38 | paraphrase | PASS → FAIL | matcher-FN flip; `Amber` vs `amber alerts` |
| 43 | relationship | PASS → FAIL | Claude named the memory (`OCR vendor review`) instead of quoting content. New rule pushed naming-over-quoting. Answer is arguably *more correct*; matcher disagrees. |
| 55 | relationship | FAIL → PASS | SUPERSEDES rule helped Claude phrase with ISO date — matcher-FN absorption |
| 71 | timeline | FAIL → PASS | matcher-FN absorption |
| 80 | relationship | PASS → FAIL | **Real Claude regression.** Baseline named `Launch checklist`; post-fix said `NO_ANSWER`. The rule made the model *more conservative* on the exact case I wanted to help. |
| 81 | relationship | FAIL → PASS | Claude pick-variance on the known idx-81 case |
| 82 | relationship | FAIL → PASS | SUPERSEDES rule helped phrasing — matcher-FN absorption |
| 87 | relationship | PASS → FAIL | Same as #43 — Claude named the memory (`Parser fallback guide`), matcher wants content quote |
| 94 | relationship | PASS → FAIL | Same as #43 — Claude named the memory (`Acoustic experiment log`), matcher wants content quote |

## Real signal

- **The directional rule did NOT fix #79** (the target case). Baseline: `NO_ANSWER`. Post-fix: Claude described the **source** of the DERIVED_FROM edge (the Cedar Idea), not the target (the OCR vendor review). The question's noun phrase ("the revised Cedar preference") matches the source node's content literally; Claude anchored on that match instead of following the edge target despite the rule. Still a miss, just a different miss.
- **#80 broke from PASS to FAIL** — the canonical DERIVED_FROM follow-on case the rule was meant to help. Strongest evidence the rule is doing harm.
- **The "fixes" are all matcher-FN absorption or pick-variance**, not real Claude gains. #55/#82 (SUPERSEDES) flipped because the prompt induced ISO-date phrasing; #22/#71 are matcher-FN; #81 is the known colloquial-relationship pick-variance.
- **The "regressions" are mostly more-correct-but-matcher-rejected**: #43/#87/#94 — Claude correctly *names* the memory the question asks for (`"Which memory ..."`); the matcher wants content quotes. The rule's "treat as concrete artifact" language pushed Claude toward naming. Same matcher-FN pattern noted in the morning's triage. #80 is the only real Claude regression.

Net real signal: 1 Claude regression (#80), 0 real Claude gains, plus a handful of matcher-FN flips that wash out.

## Decision

Reverted the prompt-rule addition. Kept the title-resolution in `_render_retrieval_context` (matches `pam.agent_interface::_plan_relationships`; no downside).

## Why this didn't work, and what would

The DERIVED_FROM follow-on case is **not** a retrieval problem (retrieval is correct — gold is rank 1 in `ordered_nodes`) and **not** a prompt-rule problem (the rule was clear; Claude didn't follow it under noun-phrase competition from the source node's content). It's a prompt-engineering ceiling on the eval renderer's surface.

What would plausibly clear it (deferred):

1. **Renderer-side edge flattening** — emit a `Derived-document index:` section with rows pre-stated in question-shape:

   ```
   Derived-document index:
   - "OCR vendor review" grew out of "Idea: Cedar OCR should remain ..."
   ```

   This converts the edge into the question's exact phrasing, removing the directional-following burden from Claude. Larger surface area (changes what every query sees), so needs broader regression check.

2. **Question-shape-aware prompt rule** — narrow the directional cue to specific question patterns (`grew out of`, `came out of`, `followed from`, `was based on`) rather than a general directional rule. Lower regression risk but more brittle.

Neither is in scope for today. Both should wait until a future eval reveals more DERIVED_FROM follow-on cases — the corpus currently has only #79 and #80, which isn't enough surface to justify the renderer churn.

## Reaffirmed feedback

This run is a textbook case of the standing feedback "Eval matcher is a triage filter — real score = matcher hits + Claude-confirmed correct misses." I was about to ship a prompt change that absorbed matcher-FNs (looked like a win) while regressing a real Claude PASS (#80). The right number to track is Claude-confirmed correctness, not matcher score.

## Files

- Reverted in `scripts/run_copilot_cli_eval.py`: prompt-rule additions in `_prompt_for_answer`.
- Kept in `scripts/run_copilot_cli_eval.py`: title-resolution in `_render_retrieval_context`.
- Eval transcripts: `test_findings/eval_runs/2026-05-13_10-07-02_*` and `2026-05-13_11-16-26_*`.
