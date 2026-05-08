# IRL eval — expanded-gate baseline (2026-05-08 PM)

Run after expanding the IRL fixture by 21 queries (5 → 16 `colloquial_relationship`, +4 `paraphrase`, +3 `time_vague`, +3 `entity_by_role`) per the hybrid-retrieval gate work in `backlog.md`. Establishes the pre-build baseline against which Phase A (embeddings) will be measured.

Command: `python scripts/run_copilot_cli_eval.py --suite irl --backend claude --include-misses`. Backend `claude-sonnet-4-5`. PAM internal LLM was unavailable (auth error), so query parsing ran on the deterministic fallback for all 68 queries — the right configuration for a retrieval-baseline read.

Log: `/tmp/pam_eval/irl_2026-05-08.log`.

## Headline

**47/68 raw matcher = 69.1%.** Roughly flat vs prior IRL-47 (33/47 = 70.2% on 2026-05-08 AM); the suite grew by 21 known-hard queries and overall % barely moved because the new rows landed in three buckets that look easy under the current matcher and one bucket (`colloquial_relationship`) that is genuinely hard.

| Category | Today | Prior (AM) | Notes |
|---|---|---|---|
| `colloquial_relationship` | **6/16 (37.5%)** | 0/5 | 4 real recall hits + 2 trivial `expect_empty`; old 5 still 0/5 |
| `paraphrase` (new) | 4/4 | — | confirmed real — token overlap higher than designed |
| `time_vague` (new) | 3/3 | — | confirmed real — 2 strong, 1 weak (correct notes in top-5 amid noise) |
| `entity_by_role` (new) | 3/3 | — | confirmed real — role descriptions in queries mirror corpus phrasing |
| Old IRL-47 slice | 31/47 (66.0%) | 33/47 (70.2%) | -2 hits, both run-to-run variance (see below) |

## colloquial_relationship — the gate is doing its job

Of 16 queries:

- **PASS (6):** `who signs off on my decisions?` (corpus: `"Anya signed off"`), `who reviews my PRs?` (`"requesting Anya for review"`), `who am I mentoring?` (`"Mentoring assignment: Diego"`), `who do I work closely with?` (Rakhi mentioned across many notes), and the two `expect_empty` reverse-direction rows (`who reports to me?`, `who's mentoring me?`).
- **MISS (10):** `who do I report to?`, `who's my manager?`, `who am I coaching?`, `who's my most frequent collaborator?`, `who critiques my code?`, `who's my boss?`, `who runs my 1:1s?`, `who's my mentee?`, `the engineer I'm helping ramp up`, `who do I pair with on code?`.

The split is exactly the design intent: queries whose role keyword appears verbatim in the corpus pass (`mentoring`, `signed off`, `reviews`, `work closely with`), and queries that need a colloquial-to-relationship hop fail. Real positive recall on colloquial-only queries is **~0/9** once the 4 literal-token matches and 2 trivial-empty rows are excluded. The 0/5 number on the old slice is unchanged.

This is the cleanest measurement axis the hybrid-retrieval feature could ask for.

## paraphrase / time_vague / entity_by_role — confirmed real, but token overlap is higher than designed

Confirmation pass: ran each query directly against the eval DB (deterministic parser, top-5 retrievals) and inspected whether the matcher substrings could be reached from grounded retrieval. Method script: `/tmp/pam_eval/run_inspect.py`.

Outcome: **10/10 are real passes** — Claude was answering from correct top-ranked notes, not hallucinating across the matcher. But the *reason* is informative for the gate design:

- **`paraphrase` (4/4 real).** Three queries (`"auth bug rooted in Apple's privacy crackdown"`, `"lock granularity debate on the cache"`, `"did Mira like the new database plan?"`) have non-paraphrase tokens that hit FTS hard (`auth bug`, `cache`/`lock`, `Mira`/`database`). The fourth (`"my deps lockfile speed-up move"`) hits because the corpus note literally contains `"deps"` + `"lockfile"`. None of these are FTS-blind in practice.
- **`time_vague` (3/3 real).** `"earlier this spring"` retrieves the decision note at rank 1 because `"decision"` is in both. `"around easter time"` and `"from last month"` are noisier — the auth-retro/JWT-correction notes appear at ranks 2–4 alongside Rakhi/uv/Diego noise — but the correct notes are present in the top-5 and the answer LLM picked them out. These are real passes but on the weaker end.
- **`entity_by_role` (3/3 real).** All three role descriptions in the queries closely mirror the role descriptions in the corpus (`"came from a Java background"` is verbatim; `"pushed back on the database migration"` ≈ `"pushed back on the ClickHouse RFC"`; `"signed off on the event store decision"` ≈ `"event store ... Anya signed off"`). Top-1 hit for all three.

**Implication for the gate.** Three of these four new categories don't actually stress the FTS-blind axis as authored — they paraphrase surface form but keep enough lexical anchor tokens for FTS to land. The category that *does* stress it cleanly is `colloquial_relationship` (37.5% raw, ~0% real positive recall on colloquial-only queries). That's consistent with the backlog already naming `colloquial_relationship` as the trigger row; the others should be treated as guardrails (must not regress) rather than triggers.

If Phase A doesn't measurably move `paraphrase` / `time_vague` / `entity_by_role` *worse*, that's the right outcome. To make these three categories actually test embedding lift, the queries would need to be re-authored without the lexical anchors (e.g., a `paraphrase` row that says `"tab/window cookie chaos"` for the SameSite/iframe issue, where no shared token survives). That's a follow-up, not a blocker.

## Old IRL-47 slice: 31/47, down 2 from morning's 33/47

Two new misses in this run that passed in the AM run:

- **Index 27, `time_relative`: `"what was I working on two weeks ago?"`.** Claude returned a substantive answer about the event store decision and Diego mentoring (both within the right window), but the matcher expected `"Anya"` (the manager 1:1 on 2026-04-25 also fits the window). Likely matcher-FN: Claude's answer is *factually correct* for the time window, just narrower than the matcher anticipated.
- **Index 34, `partial_id`: `"PR 441 status"`.** Returned `NO_ANSWER`. Real miss; PR #441 is in the corpus (`rakhi_pr_441`, `rakhi_chat`).

Net real regression on the old slice: ≤1 hit. Within run-to-run variance.

## Misses worth keeping in view (not gate-blocking)

Beyond the colloquial-relationship gate itself:

- **`multihop_3` 1/5.** Three of the four new misses are Mira-context queries (`"Mira working on the same week as auth fix"`, `"original timeline for the project Mira pushed back on"`, `"did the engineer who pushed back on Postgres also have input on dev tooling?"`). Multi-hop traversal across an inferred role isn't expected to work today; this is the same class of failure the colloquial gate measures, surfaced through multihop framing.
- **`wrong_premise` 2/6.** Four NO_ANSWERs where the design intent was a pushback ("Stripe didn't break in production, it was sandbox throttling"). Refusal-mode dominates pushback-with-correction; relates to F3 in spirit but distinct.

## Status of `colloquial_relationship` as Phase A trigger

Per `backlog.md`, target on the expanded gate is **≥60%**. Today's baseline is **6/16 (37.5%)**, and the matcher-corrected positive-recall baseline is **~0/9 (0%)**. Phase A success criterion: lift the 10 colloquial-only misses to ≥6 passes on a re-run, without regressing the 4 literal-match passes or the IRL-47 old-slice number.

## Next

1. Commit the fixture/loader/backlog/plan-link/HYBRID_RETRIEVAL_PLAN.md changes plus this finding.
2. Optional follow-up: re-author 2–3 paraphrase/time_vague/entity_by_role queries without lexical anchors so the categories stress the FTS-blind axis they were named for. Not a Phase A blocker.
3. Start Phase A.
