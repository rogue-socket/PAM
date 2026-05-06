# Regression suite re-run — 2026-05-07

Sequential re-run of the regression eval that was rate-limited yesterday. Goal was to confirm the matcher-fix lift over the 8/20 baseline.

## Result

**11/20 = 55%**, up from 8/20 = 40% baseline. Lift of +3 queries / +15pp — well short of the +9 lift yesterday's analysis predicted.

Command:

```
PAM_LLM_PROVIDER=claude_code python scripts/run_copilot_cli_eval.py \
    --suite regression --backend claude --batch-size 5
```

(env: `pam-test`, model: `claude-sonnet-4-5` answer side, `claude-haiku-4-5` parser side, no Anthropic API key)

## Why the lift was smaller than predicted

The bidirectional containment fix from yesterday catches *terse* correct answers (`"Reykjavik annex"` ⊆ `"the Reykjavik annex"`). But the regression corpus's expected strings carry filler prefixes and rewording that makes both forward (expected ⊆ answer) and reverse (answer ⊆ expected) fail — the answer is *longer* than expected (LLM elaborates) but doesn't reproduce the filler verbatim.

### The 9 misses, by failure mode

| Q | Failure mode |
|---|---|
| 2 | Expected has `"Thought:"` / `"Good evaluation includes"` filler prefix; answer drops it |
| 3 | Expected uses `;` separator; answer uses `(parenthetical), while` |
| 4 | Answer rewords expected (all keywords present, no contiguous substring) |
| 6 | Expected has `"matter because they"` filler; answer drops it |
| 9 | Answer is `"50"` (1 token) — gated out by `_TERSE_ANSWER_MIN_TOKENS = 2` |
| 10 | `"Thought:"` prefix in expected; synonym variants (`"tools"` vs `"systems"`) |
| 11 | Answer gave memory title; expected wants content phrase. Schema mismatch — real |
| 14 | Expected ends with `.`; answer wraps same string in quotes with no trailing `.` |
| 16 | `"File ingestions default to..."` vs expected `"File ingestion defaults to..."` (plural/singular) |

8/9 are matcher gaps; 1 (Q11) is a real corpus-design issue (`"Which memory mentions X?"` queries don't fit substring matching cleanly).

## Options to close the gap

### Option A — Fix the corpus
Shorten `expected_substrings` in `tests/fixtures/retrieval_regression_corpus.json` to the load-bearing core phrase (drop `"Thought:"` prefixes, trailing `.`, restructure verbose expecteds). Risk: weakens the test bar.

### Option B — Smarter matcher
Add normalization rules: strip leading `"Thought:"`, strip trailing punctuation, lemmatize plurals, drop `_TERSE_ANSWER_MIN_TOKENS` gate or lower to 1. Risk: each rule chips at signal, could pass false positives.

### Option C (recommended) — Surgical combination
1. Strip leading `"Thought: "` from expected at canonicalization time (presentation artifact).
2. Strip trailing `.` from canonical expected before substring check.
3. Lower `_TERSE_ANSWER_MIN_TOKENS` from 2 to 1; rely on the existing `if not canonical_expected: continue` check to handle empty/stop-word degeneracy.

Predicted lift: catches Q2, Q9, Q14 → **14/20 = 70%**.

Q3, Q4, Q6, Q10, Q16 remain — these need either:
- Corpus tightening per-query (drop filler in those expecteds), or
- A more aggressive matcher (token-set / Jaccard / fuzzy), which yesterday's lessons-learned doc warns against because it conflates correct and confidently-wrong answers.

Q11 is a real retrieval/answer issue tied to `"Which memory mentions X?"` query schema — needs a different mitigation (return memory titles in answer, or change the eval expectation).

## Status

Diagnosis only. No code changes this session. Resume from Option C when ready.
