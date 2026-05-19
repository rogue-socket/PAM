# IRL fix sequence — 2026-05-19 session summary

**Start**: 57/68 = 83.8% (baseline `2026-05-19_10-20-00_irl_claude.json`)
**End**:   63/68 = 92.6% (final run `2026-05-19_11-19-57_irl_claude.json`)
**Net**:   +6 queries / +8.8 percentage points / 2 commits

## What shipped

### Commit `e6867a8` — wrong-premise correction + miss classification

Two threads bundled.

1. **Wrong-premise correction rule** added to both prompts:
   - `pam/chat_agent.py:build_chat_prompt` (production)
   - `scripts/run_copilot_cli_eval.py:_prompt_for_answer` (eval)

   When the retrieved context directly contradicts the question's premise (wrong attribution, wrong environment, asserted-thing-didn't-happen), state the contradiction instead of punting to NO_ANSWER / "I don't know from PAM memory."

   **Impact**: 57→60 (+3). idx 18 (Diego/auth), 19 (Stripe/prod), 21 (Anya/cache) flipped to PASS.

2. **Miss classification** (pre-existing pending work, bundled): the eval harness now tags each miss as `subprocess_error / false_positive / retrieval_miss / partial_surface / pick_miss` from `expected_substrings` + `retrieved_context`.

### Commit `090346d` — time-relative fallback when window has zero hits

Three coordinated changes.

1. **`pam/retrieval/query_parser.py`**: new `time_range_relative: bool` field on `ParsedQuery`. `_extract_time_range_with_meta` returns whether the source phrase was relative (last week / yesterday / today / this week). Wired through `fallback_parse` and `_normalize_parsed_query`.

2. **`pam/retrieval/search.py`**: in `_time_range_seed_candidates`, when the windowed query returns zero rows AND the window was relative, run a no-filter recent-N query (rank −35.0, below windowed rank −30.0). Also fixed a pre-existing typo where `not parsed.keywords` had inverted the guard.

3. **Both prompts**: added a rule — when a relative time window contains no items, summarize the most recent activity and note the gap, don't punt.

   **Impact**: 60→63 (+3). idx 20, 25, 27, 32 flipped to PASS. One matcher-FN regression on idx 18 ("didn't decide" vs expected "did not decide") and one variance flip on idx 57.

## What was attempted and reverted

### Fix #3 — multi-hop entity bridge for idx 15

Goal: surface the original ClickHouse RFC ("Estimated 3 weeks") when asked "what was the original timeline for the project Mira pushed back on?".

Diagnostic finding: the eval ingest mocks `extract_entities` to `[]` (deterministic-only path), so the graph has **zero entity nodes** — there's no ClickHouse entity for the expander to bridge through. The current architecture makes entity extraction LLM-only.

Attempted: deterministic NER fallback in `pam/ingestion/pipeline.py:_run_llm_enrichment` — extract capitalized proper nouns by frequency, tag as `concept`, link via `link_entities_detailed`.

Result: **−6 queries** (63→57). The NER created 43 entity nodes (right ones: Mira, Anya, Diego, Rakhi, ClickHouse, Postgres, Safari, SameSite, Chrome, Firefox; noise: GIL, Old, Earlier, Latency, Login). The noise crowded the relationship section of retrieval output, displacing the actual notes for many previously-passing queries. And idx 15 itself stayed broken — the `rfc_clickhouse` source-type node was REFERS_TO ClickHouse via the deterministic edge, but the graph expander didn't traverse to it from the Mira-pushback note.

Reverted in working tree (no commit). idx 15 stays open.

## Remaining misses (5)

| idx | type | what it needs |
|---|---|---|
| 15 | multihop_3 | A graph-native fix: real LLM entity extraction + an expander that traverses REFERS_TO into source-type nodes. The deterministic-NER shortcut doesn't substitute. |
| 18 | wrong_premise | Matcher artifact only — the model answered correctly ("Diego didn't decide... was shadowing") but the matcher requires literal "did not decide". Widen expected_substrings in the fixture. |
| 33 | colloquial | Synonym recall: question says "critiques", corpus says "review". `auth_pr_event` ("requesting Anya for review") not retrieved. |
| 56 | colloquial | Lexical pull: "pair" → Diego's mentoring note ("Plan: pair on a real bug") instead of Rakhi's actual coding collaboration. |
| 57 | colloquial | Edge-direction: "who reports to me" → "Anya" (Anya is the user's manager). Needs a typed MANAGED_BY edge or a prompt-level direction guard. |

The three colloquial misses cluster around the same gap: PAM has no aggregation-by-role primitive, and FTS doesn't bridge critique↔review or future-pair↔past-collaborate.

## Per-type final state

| type | hits/total | notes |
|---|---|---|
| vague | 5/5 | |
| multihop_2 | 5/5 | |
| typo | 1/1 | |
| casual | 5/5 | |
| multihop_3 | 4/5 | idx 15 needs LLM entity extraction |
| multihop_4 | 1/1 | |
| wrong_premise | 5/6 | idx 18 is a matcher artifact |
| demanding | 4/4 | |
| time_relative | 3/3 | (all green after fix #5) |
| out_of_blue | 1/1 | |
| colloquial_relationship | 13/16 | idx 33, 56, 57 open |
| partial_id | 2/2 | |
| negative | 4/4 | |
| paraphrase | 4/4 | |
| time_vague | 3/3 | |
| entity_by_role | 3/3 | |

## Score arithmetic for remaining lift

- +1 (idx 18 matcher widen) → 64/68 = 94.1%
- +1 (idx 57 direction guard) → 65/68 = 95.6%
- +2 (idx 33, 56 synonym recall) → 67/68 = 98.5%
- +1 (idx 15 graph-native bridge) → 68/68 = 100%

The first two are tractable in <30 min each. idx 33/56 is a real design lift (synonym recall is the underlying gap). idx 15 is the principled graph-native test the suite was built for and remains the most informative open miss.
