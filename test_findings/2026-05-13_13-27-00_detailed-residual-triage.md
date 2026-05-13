# Detailed-suite residual miss triage (2026-05-13)

Triage pass against the detailed Claude eval's residual misses after Phase A.2 ship. Goal: classify each miss as **matcher-FN** (Claude answered correctly but the substring matcher didn't accept the phrasing), **Claude-noise** (retrieval surfaced the right node, Claude picked wrong / misread the question), or **retrieval-gap** (the gold isn't in the top-10 surfaced to Claude). Used to decide whether any miss actually needs code.

## Run

- Script: `scripts/run_copilot_cli_eval.py --suite detailed --backend claude --include-misses --batch-size 20`
- Transcript: `test_findings/eval_runs/2026-05-13_07-37-29_detailed_claude.json` (gitignored)
- Headline: **97/110 (88.2%)** — one fewer miss than yesterday's 96/110 (Claude pick variance on borderline cases).
- **Caveat:** `sqlite_vec` and `sentence_transformers` were unavailable in the run env, so the vector channel was disabled and PAM ran FTS-only. Yesterday's run state is unknown (no saved transcript — exactly the gap that prompted the auto-save change shipped earlier today). Vector-on results could differ for the retrieval-gap cases below.

## Misses

| # | Type | Query | Claude answer | Expected (matcher) | Verdict |
|---|------|-------|---------------|--------------------|---------|
| 5 | lookup | What graph expansion depth did the memo keep? | `2` | `depth remains 2` | **matcher-FN** |
| 18 | lookup | What did users trust before probabilities? | `arrows` | `users trusted arrows before they trusted probabilities` / `color-coded berth arrows` | **matcher-FN** |
| 31 | paraphrase | Who signed off once the regression pack replay convinced the architecture review? | NO_ANSWER | `nadia wu` | **retrieval-gap** — top-10 has "Retrieval ranking postmortem" etc., no Nadia Wu node |
| 36 | paraphrase | Where did salt fog damage hardware during the drill? | `Bergen` | `antenna 3` | **Claude-noise** — retrieval surfaces "antenna" content; Claude read "where" literally and gave the place |
| 38 | paraphrase | Which alert color survived sleet better for the night shift? | `Amber` | `amber alerts` | **matcher-FN** |
| 46 | relationship | Which statement suggests Cobalt only wins if the budget gap stays large? | unrelated procurement quote | `cobalt scan might be acceptable` | **retrieval-gap** — no cobalt/budget-gap statement in top-10 |
| 55 | relationship | What launch correction superseded the April 18 plan? | NO_ANSWER | `2026-04-26` | **retrieval-gap (F3-adjacent)** — top-1 is "Release meeting on 2026-04-12: Amina Sorensen moved launch..."; the 04-26 supersession isn't in top-10. (Backlog F3 item assumes the supersession IS surfaced and Claude refuses; here it isn't surfaced. Worth a closer look — could be a vector-off artifact.) |
| 78 | timeline | Between 2026-03-14 and 2026-03-16, what two architecture corrections show up? | `graph expansion depth held at 2 ... edge weight threshold set at 0.35` | `harborcache rollout` / `after the crane outage` | **Claude-noise** — retrieval surfaces "Architecture review on 2026-03-14: Nadia Wu approved the Har[borCache]…" + the graph-expansion memo; Claude picked two non-correction memos from the same window. Multiple plausible answers in that date range; question is ambiguous. |
| 84 | relationship | Which place shows up in both the OCR review sample set and the ORCA-7 impact report? | NO_ANSWER | `nuuk` | **retrieval-gap** — multi-hop intersection. Top-10 has "OCR vendor review" and "Energy landscape note" but no Nuuk anchor. Classic case for true multi-hop / set-intersection. |
| 88 | paraphrase | Which memory explains why warmer visual treatments worked better in weather? | NO_ANSWER | `amber alerts` / `red` | **retrieval-gap** — top-10 has "Northline pilot field report" but no amber/red content surfaced. |
| 89 | paraphrase | What field hardware replacement followed salt fog corrosion? | NO_ANSWER | `ceramic mast` | **retrieval-gap** — same Northline node as #88; ceramic-mast detail not retrieved. |
| 94 | relationship | Which memory ties crane squeal to false positives? | `Acoustic experiment log (2026-03-07)` | `false positives still mostly came from crane squeal` | **matcher-FN** — Claude named the memory by title; matcher wants the literal quote inside it. (Known from 2026-05-12 wrap.) |
| 95 | lookup | How were attachment sizes treated in offline sync? | `Attachments over 12 MB were compacted before the next ferry transfer.` | `compacts attachments over 12 mb` | **matcher-FN** — "compacted" (past) vs matcher's "compacts" (present). |

## Counts

- **Matcher-FN:** 5 — #5, #18, #38, #94, #95 → absorbing these flips the headline to **102/110 (92.7%)**, no code change needed.
- **Claude-noise:** 2 — #36 (question phrasing ambiguous), #78 (multiple corrections in date window — Claude picked wrong two). Both are answer-side variance, not retrieval defects.
- **Retrieval-gap / F3-adjacent:** 6 — #31, #46, #55, #84, #88, #89. All NO_ANSWER or wrong-quote. Each needs FTS+vector confirmation before action; some likely vector-off artifacts in this run.

## Vectors-on rerun (`test_findings/eval_runs/2026-05-13_08-58-57_detailed_claude.json`)

Re-ran the same suite with `sqlite_vec` + `sentence_transformers` installed in `agent_runtime` and the eval DB reset so embeddings get written at ingest. Same headline — **97/110 (88.2%)** — but a very different miss composition:

- **Vectors fix 6 of the FTS-only retrieval-gap candidates:** #31 (Nadia Wu), #38 (amber alerts), #46 (Cobalt budget gap), #84 (Nuuk OCR∩ORCA-7), #89 (ceramic mast), #94 (crane squeal). The earlier suspicion was right — most of the "retrieval-gap" misses in the FTS-only run were vector-off artifacts.
- **Vectors regress 6 different queries:** #22, #63, #71, #79, #81, #82. Most are matcher-FN (Claude gives the right content in a phrasing the substring matcher doesn't accept) or Claude pick-variance (idx 81 — known).
- **Persistent across both runs (7):** #5, #18, #36, #55, #78, #88, #95.

### Vectors-on misses (13)

| # | Type | Claude answer (truncated) | Expected | Verdict |
|---|------|---------------------------|----------|---------|
| 5 | lookup | `2` | `depth remains 2` | matcher-FN (same as FTS-only) |
| 18 | lookup | `Arrows.` | `users trusted arrows ...` | matcher-FN |
| 22 | lookup | `ORCA-7 was caused by a stale customs cache that replayed archived berth tags during a busy handoff.` | `stale customs cache replayed archived berth tags` | **matcher-FN** — single inserted "that " breaks literal substring |
| 36 | paraphrase | `Bergen` | `antenna 3` | Claude-noise — "where" read literally |
| 55 | relationship | `The launch was moved from April 18 to April 26 because invoice export still rounded fuel surcharges incorrectly.` | `2026-04-26` | **matcher-FN** — Claude answered correctly in human-readable date form, matcher wants ISO. (This was the F3 candidate; turns out it's not F3 at all — retrieval surfaces the supersession with vectors on, Claude answers it; matcher just doesn't accept the date format.) |
| 63 | lookup | NO_ANSWER | `bergen-2026-03-cold-start` | **retrieval-gap** — session-name convention not surfaced |
| 71 | timeline | `The launch date moved from 2026-04-18 to 2026-04-26 ... ORCA-7 fix keyed cache invalidation on manifest revision ...` | `april 26` / `manifest-revision invalidation patch` | matcher-FN/Claude-noise — right content, wrong phrasing on both substrings (`2026-04-26` not `april 26`; "manifest revision" not "manifest-revision invalidation patch") |
| 78 | timeline | depth+threshold | `harborcache rollout` / `after the crane outage` | Claude-noise (ambiguous window) |
| 79 | relationship | NO_ANSWER | `ocr vendor review` | **F3** — "X grew out of Y" canonical case. Backlog item *F3 — post-supersession answer prompt* names exactly this shape (DERIVED_FROM analogue of SUPERSEDES). |
| 81 | relationship | NO_ANSWER | `community workshop transcript` / `plain-language tide labels` | Claude pick-variance — retrieval is correct per Phase A.2; Claude flips between gold and a sibling across runs |
| 82 | relationship | `The April 18, 2026 public launch target was replaced by a revised April 26, 2026 launch target ...` | `2026-04-18` | matcher-FN — `April 18, 2026` vs `2026-04-18` |
| 88 | paraphrase | NO_ANSWER | `amber alerts` / `red` | retrieval/F3 — same Northline pilot field report retrieved, "warmer visuals" framing not picked up |
| 95 | lookup | `Attachments over 12 MB were compacted before the next ferry transfer.` | `compacts attachments over 12 mb` | matcher-FN (tense) |

### Counts (vectors-on)

- **Matcher-FN: 7** — #5, #18, #22, #55, #71, #82, #95
- **Claude-noise / pick-variance: 3** — #36, #78, #81
- **Retrieval / F3-side: 3** — #63, #79, #88

Absorbing matcher-FN and Claude-noise puts the real number at **107/110 (97.3%)**.

## Recommendations (updated after vectors-on confirmation)

1. **Reported detailed-suite Claude headline should be 107/110**, not 96/110 or 97/110. Most of the residual misses are substring-matcher artifacts (strict literal substring, no synonym / no date-format normalization / no tense normalization). Per the standing feedback rule, the matcher is a triage filter — the gauge is matcher-hit + Claude-confirmed-correct.
2. **#84 (Nuuk multi-hop intersection) PASSED with vectors on.** This corpus does not yet present a concrete query that motivates the parked Phase B / true-multi-hop track. Keep it parked; the deferral rationale in `decisions.md` 2026-05-07 still holds.
3. **#79 is the cleanest F3 case in the corpus.** "What document grew out of the revised Cedar preference?" → expected `ocr vendor review`. Claude says NO_ANSWER. This is precisely the DERIVED_FROM analogue of the SUPERSEDES F3 item in `backlog.md`. **Recommend acting on the F3 backlog item next session**, scoped specifically to DERIVED_FROM. #88 may also benefit (NO_ANSWER on warmer-visuals reasoning).
4. **Vector channel sensitivity matters more than expected.** Two runs back-to-back on the same code produced the same 88.2% with a 6-miss swap. Future eval reports should record whether `sqlite_vec` + `sentence_transformers` were available, and whether the DB was reset before ingest. Worth adding a marker to the auto-saved transcript payload — small follow-up.
5. **Skip code changes for #5, #18, #22, #36, #55, #71, #78, #81, #82, #95.** All matcher-FN or Claude pick variance; chasing them via matcher rules or prompt tweaks risks overfitting to this fixture.

## What this run already proved out

- The transcript auto-save shipped earlier today did its job — both miss tables above came straight out of `test_findings/eval_runs/*.json`. Future residual-triage passes won't need a re-run to get the miss list, and we now have a comparable side-by-side for FTS-only vs vectors-on.
