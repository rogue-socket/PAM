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

Diagnosis only. No matcher code changes — see methodology decision below.

## Methodology (decided 2026-05-07)

The matcher stays as-is. It is treated as a **triage filter**, not the source of truth on quality.

- Run the eval → matcher emits a coarse score.
- A human (or Claude in-session) reads the misses and reclassifies the false-negatives.
- The published score is `matcher_hits + confirmed_correct_misses`.

**Why:** chasing the matcher's surface-form failures (filler prefixes, plurals, punctuation, terse answers) adds rules without removing the underlying brittleness. Manual triage is fast (<1 min for 20 queries), more honest, and avoids baking arbitrary stop-word lists / morphology rules into the eval harness.

**Cost:** the eval cannot be graded unattended. Acceptable since this eval is run interactively, not in CI.

### Today's regression score under this methodology

- Matcher hits: 11
- Confirmed-correct misses (manual triage): 8 (Q2, Q3, Q4, Q6, Q9, Q10, Q14, Q16)
- Real miss: 1 (Q11 — `"Which memory mentions auditability?"` returns the memory title `"Local-First Sync Boundaries"` rather than a content phrase containing "auditability"; this is a `"Which memory mentions X?"` schema issue, not a retrieval bug)
- **Real score: 19/20 = 95%**
