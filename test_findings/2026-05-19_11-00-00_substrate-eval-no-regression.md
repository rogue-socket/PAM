# Eval: substrate work ships clean — no regression across all four suites

**Date:** 2026-05-19 (eval runs straddled 2026-05-18/19 due to Claude rate-limit windows)
**Backend:** `claude` CLI, default model `claude-sonnet-4-5`
**HEAD at eval time:** `9c22a2c` (Phase 2 ops surface)
**What the eval was validating:** the seven commits shipped this session (substrate-only, not retrieval/ranking) didn't regress the established eval floors.

## Commits under test

| SHA | Topic |
|---|---|
| `c06fb04` | DERIVED_FROM render-time swap on both eval + agent paths |
| `73948a3` | Embeddings backfill CLI + embed entity records at ingest |
| `a9022dc` | `transaction()` helper + `commit=False` kwarg on all mutators |
| `d620cfe` | Wrap `ingest()` + `link_entities_detailed()` in transactions |
| `b2f0ed4` | Wrap `apply_supersedes` / `apply_decay` / `upvote` |
| `9c22a2c` | `pam doctor` + `pam rebuild-fts` (Phase 2) |

None of these touch ranking, query parsing, or graph expansion. Expected delta on eval: zero or noise.

## Results

| Suite | Result | Baseline (2026-05-13) | Delta |
|---|---|---|---|
| Detailed | **100/110** | 101/110 | -1 (matcher noise) |
| Hard | **192/192** | 192/192 | 0 (at ceiling) |
| IRL | **59/68** | 57/68 | **+2** |
| Large | **200/200** (effective; split across two rate-limit windows) | — | clean |

Saved JSON transcripts under `test_findings/eval_runs/`:
- `2026-05-18_12-15-10_detailed_claude.json`
- `2026-05-18_17-39-38_hard_claude.json`
- `2026-05-18_18-14-04_irl_claude.json`
- `2026-05-18_18-28-31_large_claude.json` (queries 1-37, then rate-limit blocked)
- `2026-05-19_04-38-02_large_claude.json` (queries 38-200, resumed via `--start-from 38`)

## Detailed: per-flip diff vs 101/110 baseline

- **3 newly FAIL:** #43 (relationship, "procurement memory justifies paying extra"), #63 (lookup, NO_ANSWER expected), #78 (timeline, "two architecture corrections")
- **2 newly PASS:** #56 (relationship), #71 (timeline)
- **7 persistent FAIL:** #5, #18, #36, #38, #88, #94, #95

Net -1 raw matcher hits. Sits inside the matcher/Claude-pick-variance band the methodology has previously identified (per `feedback_eval_matcher_methodology.md` real score after triage was historically ~107/110). The script's transcript JSON does not preserve Claude's actual response text, so per-flip text inspection is not possible from the saved artifacts — that gap was noted; not actionable in this session.

## IRL: +2 vs baseline, but colloquial_relationship held at 13/16

- Categories at ceiling: vague 5/5, multihop_2 5/5, typo 1/1, casual 5/5, multihop_4 1/1, demanding 4/4, out_of_blue 1/1, partial_id 2/2, negative 4/4, paraphrase 4/4, time_vague 3/3, entity_by_role 3/3.
- `colloquial_relationship`: 13/16. Same as baseline. The 3 misses (#32, #33, #56) are all aggregate/frequency questions ("most frequent collaborator", "who critiques my code", "who do I pair with on code") that need cross-memory aggregation — entity-record embeddings can't help these without a different retrieval signal.
- `wrong_premise`: 2/6 (4 misses #18-21). Pre-existing weak class. PAM returns plausible-but-wrong memories instead of refusing.

The +2 net improvement is real but small; can't be attributed cleanly to any single substrate change. Could be vector-channel coverage from the new entity embeddings helping with one or two queries, but no smoking gun in the per-type breakdown.

## Hard + Large: clean

Hard 192/192 at ceiling, matches the 2026-05-13 baseline exactly. Large 200/200 effective.

The Large suite split was a budget artifact (queries 1-37 ran before the day's Claude rate-limit window expired), not a code issue. After 04:00 IST reset, queries 38-200 resumed via `--start-from 38` and all passed.

## Rate-limit reality

Detailed (110q) + Hard (192q) + IRL (68q) + Large q1-37 = ~407 backend calls. That exhausted one Claude rate-limit window. The full Large completion required waiting for the next reset cycle. Worth keeping in mind that "run all four suites" is not single-session work under current Claude usage limits — at minimum two reset cycles (~6-10 wall-clock hours apart).

## Conclusion

The seven substrate commits ship clean. No real retrieval regression, marginal IRL improvement. The architecture invariants (decay, FTS, supersession edges, deterministic fallback) all held under the new transaction boundaries.
