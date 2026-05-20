# Glossary

Project-specific terms an outside agent wouldn't know. PAM-specific or eval-specific only — no general vocabulary.

## Product / context

- **PAM** — Personal Agent Memory. The local-first SQLite-backed memory store this repo implements.
- **kayo** — the consuming personal-assistant agent that uses PAM as its memory layer. Many design choices ("kayo's Copilot subprocess", "kayo cannot calibrate confidence") refer to this consumer.
- **graph-native** — the intended end state: retrieval driven by graph relationships and path provenance rather than FTS-led keyword matching. Today's code is "FTS-led, relation-aware"; that distinction is load-bearing — see `docs/ARCHITECTURE.md`.
- **claude_code provider** — `LLM_PROVIDER=claude_code` mode. PAM shells out to the local `claude` CLI instead of using an Anthropic API key. Lets PAM run with no API keys.
- **deterministic fallback contract** — the invariant that ingest and query parsing must keep working when LLM SDKs are missing or fail. Locked by `tests/test_deterministic_fallback.py`.

## Storage / model

- **workspace_id** — first-class scope key on every node. Defaults to resolved CWD. Dedupe and entity linking are scoped to it. *Distinct from the LLM-call working directory* (`cwd`) — see `pam/chat_agent.py`.
- **node statuses** — `active` | `draft` | `reference` | `archived`. Draft entities are graph bridges but aren't surfaced as direct results. Superseded nodes flip to `reference` (not `archived`).
- **edge relations** — the dependable minimum: `REFERS_TO` (note/event → entity), `DERIVED_FROM` (note → source), `RELATED`, `CONTRADICTS`, `SUPERSEDES`. Adding new kinds requires write-time rules dependable enough to maintain graph quality.
- **score_components** — the per-node breakdown returned in `RetrievalResult.score_components`: `{text_relevance, vector_similarity, recency, importance, entity_bonus}`. The five entries sum exactly to the rank-key, plus an optional `derived_propagation` entry when `DERIVED_FROM` score propagation fires. Added by audit O8.
- **valid_at vs updated_at** — `valid_at` is the in-world time the memory describes; `updated_at` is the last DB write. Decay uses `updated_at`; recency filtering and ranking use `valid_at`. Don't confuse them.

## Eval

- **detailed / hard / large / regression / IRL** — the five eval suites in `tests/fixtures/`. Detailed is templated lookup-heavy; hard and large are templated multi-relation; regression is `tests/fixtures/retrieval_regression_corpus.json`; IRL is hand-built naturalistic queries (see `docs/EVAL_SUITES.md`).
- **matcher false-negative** — eval-harness substring matcher rejects an answer that is in fact correct (e.g., terse answer, plural, prefix mismatch). Drives the "matcher is a triage filter" methodology.
- **triage filter** — the role of the substring matcher per the 2026-05-07 decision. Real published score = matcher hits + Claude-confirmed correct misses after manual triage.
- **F3** — known issue from the 2026-05-06 audit: post-supersession queries (e.g., `"What target did X move to?"`) where retrieval surfaces the new node but the answer prompt refuses because the new note title reads as tentative ("Idea: revise X to Y…"). Fix is in the answer prompt, not retrieval.
- **Q14, Q21, Q24, Q25** — recurring IRL miss IDs:
  - **Q14** — `"what was Mira working on the same week as the auth fix push?"` Multi-hop temporal-proximity reasoning. Not solved by graph traversal; needs date-anchored retrieval.
  - **Q21** — `"what did I do last week?"` Retrieval is correct; answer prompt reads third-person notes as "not about me" and returns NO_ANSWER. Prompt-side fix.
  - **Q24** — `"who do I report to?"` The target note is `"1:1 with Anya"` — zero token overlap with role-question vocabulary. The canonical example of why FTS-led retrieval can't handle colloquial-relationship queries. See `backlog.md` for the colloquial-relationship test-corpus expansion.
  - **Q25** — `"PR 441 status"`. Partial-id query; FTS-side limitation.

## Audit / housekeeping

- **O1–O8** — the 2026-05-06 audit's open-items numbering. Closed items are tagged `*(closed YYYY-MM-DD)*` in `audits/2026-05-06_*_audit.md`. As of 2026-05-08: O1, O2, O3, O4, O5, O6, O7a, O8 closed. O7b/O7c deferred (see decisions).
- **cue patterns** — regex patterns at `pam/ingestion/pipeline.py` that detect relationship cues at ingest time (`SUPERSEDES_CUE_PATTERN`, `DERIVED_FROM_CUE_PATTERN`, `CONTRADICTS_NEGATIVE_CUE_PATTERN`). These drive write-time edge inference.
- **`apply_supersedes`** — the unified helper at `pam/relations.py` that all SUPERSEDES write paths now call. See decision 2026-05-07.

## Retrieval primitives

- **FTS5** — SQLite's full-text search module. PAM's primary lexical retrieval channel; vector similarity over the `vec_nodes` table runs as a parallel channel and is merged with FTS candidates. FTS5 tokenizes on non-alphanumeric, which is why `"1:1"` doesn't index usefully.
- **graph expansion** — the second-pass step in `pam/retrieval/graph_expander.py:expand` that adds nodes reachable via specific edges from the FTS candidates. Currently a fixed traversal pattern, not a depth-bounded BFS — see decision 2026-05-07 (O7a).
- **answer_mode** — `"node"` | `"relationship"`. Field on `ParsedQuery`. `"relationship"` mode favors edge-bearing answers. See `pam/retrieval/query_parser.py`.
- **intent** — `"lookup"` | `"timeline"` | `"summarize"` | `"reason"`. Field on `ParsedQuery`. `"reason"` triggers RELATED-chain expansion in the graph-expander.
