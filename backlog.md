# Backlog

Open work that doesn't belong in the dated audit/test_findings, isn't on a current sprint, but shouldn't get lost. Each item should be specific enough to act on cold.

When an item gets picked up, move it into a session doc or `audits/` / `test_findings/` and remove it from here.

---

## Eval / quality

### [next] Widen IRL fixture matcher for idx 18 <!-- from: test_findings/2026-05-19_23-37-01_irl_fix_sequence_summary.md -->
**Why:** After the wrong-premise prompt rule landed (commit `e6867a8`), idx 18 ("what did Diego decide about the auth refactor?") is answered correctly by the model ("Diego didn't decide anything... was shadowing you") but the fixture matcher expects literal "did not decide" / "shadowed". Same answer, stricter matcher. One-line change to `tests/fixtures/irl_eval_corpus.json` for query 18 to accept contractions / verb-form variants. Worth +1 query on IRL (63/68 → 64/68 = 94.1%).
**How to apply:** add "didn't decide" / "didn't" / "shadowing" alongside the existing substrings, or convert to a regex form that accepts either form.

### Typed MANAGED_BY edge for management-direction queries <!-- from: test_findings/2026-05-19_23-37-01_irl_fix_sequence_summary.md, prompt guard shipped 2026-05-20 -->
**Why:** The prompt-level guard for idx 56/57 shipped 2026-05-20 — `pam/chat_agent.py` and `scripts/run_copilot_cli_eval.py` both now refuse to infer reportee status from 1:1 framing / sign-off / "asked me to" patterns. That's the cheap fix. The principled long-form fix is still open: at ingest time, scan for cues like "1:1 with X" + "X signed off" + "X said Y is on track" and emit a typed `MANAGED_BY` edge so the graph itself carries direction. Then any query about management relationships can lean on graph structure instead of prompt rules.
**How to apply:** (a) add `MANAGED_BY` to the edge relation set; (b) write-time cue rules in `pam/ingestion/extract.py` or `pam/ingestion/pipeline.py` to emit the edge from explicit phrasing patterns; (c) expander updates so reportee queries traverse incoming MANAGED_BY edges; (d) retire the prompt guard once the graph signal is reliable. Real work, not a one-line change — pick this up when another management-direction query surfaces in evals.

### Colloquial-relationship synonym recall (idx 33, 56) <!-- from: test_findings/2026-05-19_23-37-01_irl_fix_sequence_summary.md -->
**Why:** Two queries miss because of synonym gaps: "who critiques my code" expects Anya but auth_pr_event uses "requesting Anya for review" (critique↔review not bridged); "who do I pair with on code" expects Rakhi but the word "pair" lexically pulls Diego's mentoring note ("Plan: pair on a real bug first"). Worth +2 queries on IRL (65/68 → 67/68 = 98.5%).
**How to apply:** write-time cue rules in `pam/ingestion/extract.py` or `pam/ingestion/pipeline.py` to emit explicit synonym edges (REVIEWS / COLLABORATES_ON) on phrasing matches, and/or embedding-side recall tuning. Also needs a "future-tense vs past-tense" signal so "Plan: pair on…" doesn't outweigh "We sketched per-key locks". Pairs naturally with the multi-hop graph-native work.

### Per-stage miss categorization (retrieval vs expansion vs ranking vs rendering) <!-- from: DEPENDABILITY_PLAN.md Phase 2, partial-ship 2026-05-19 -->
**Why:** A coarse 5-class textual classifier shipped 2026-05-19 (`scripts/run_copilot_cli_eval.py::_classify_miss` → `subprocess_error` / `false_positive` / `retrieval_miss` / `partial_surface` / `pick_miss`). The DEPENDABILITY_PLAN Phase 2 vision is finer: distinguish *retrieval-miss* from *expansion-miss* from *ranking-miss* from *rendering-miss*. Today these all collapse into `retrieval_miss` because the classifier only sees the final rendered context, not per-stage outputs.
**How to apply:** either (a) augment each fixture entry with a gold node ID and have the classifier query PAM stage-by-stage (FTS candidates → graph_expander → ranker → renderer) checking presence at each stage, or (b) instrument `pam/retrieval/search.retrieve()` to return per-stage debug info in `query_meta` and have the harness consume it. Pick this up when `retrieval_miss` becomes the dominant class in real eval runs — until then, the 5-class split is enough triage signal.

---

## Architecture / roadmap

### True multi-hop graph traversal *(O7c)* <!-- from: docs/BACKLOG.md, IRL idx 15 confirms 2026-05-19 -->
**Why:** `pam/retrieval/graph_expander.py:258` carries a TODO for constrained multi-hop with path provenance. Today's expander does a fixed traversal pattern. IRL idx 15 ("what was the original timeline for the project Mira pushed back on?" → expects "3 weeks" from `rfc_clickhouse`) is the first eval query that obviously fails on this gap: the expander does not traverse REFERS_TO into source-type nodes, and the answer "3 weeks" lives in a source-type RFC node.
**How to apply:** (a) extend the expander to traverse REFERS_TO into source / file node types, not just note / event; (b) add explicit path provenance so the answer prompt can cite "Mira → ClickHouse → rfc_clickhouse"; (c) the 2026-05-19 deterministic-NER attempt (see test_findings/2026-05-19_23-37-01) proved a regex NER fallback is NOT a viable substitute — it adds noise without bridging to source-type nodes. The principled fix needs the real LLM extraction path in the eval ingest (currently mocked) OR a different graph-aggregation primitive.

### [blocked: needs LLM entity extraction in eval ingest] Live-LLM ingest variant for graph-native evals <!-- from: test_findings/2026-05-19_23-37-01_irl_fix_sequence_summary.md -->
**Why:** `scripts/run_copilot_cli_eval.py:_ingest_fixture` mocks `extract_entities → []`, `summarize → ""`, `generate_edge_fact → ""` so the eval tests deterministic retrieval, not LLM enrichment. This means the eval can never exercise the graph-native bridge that idx 15 (and future multi-hop queries) need. A separate `--suite irl-graph` invocation that does NOT mock these calls would let us measure the graph-native ceiling.
**How to apply:** parameterize `_ingest_fixture` with a flag like `mock_llm=True/False`; add a new SUITE_SPEC entry that runs with `mock_llm=False` against the same IRL corpus. Costs one rate-limit window per run.

---

## Code housekeeping (low-priority)

### Confirm answer-side default model <!-- from: ~/.claude/sessions/PAM/2026-05-07.md -->
**Why:** `CHAT_ANSWER_MODEL` defaults to `claude-sonnet-4.5` in `config.py`. Alternatives the user named: `claude-opus-4`, `gpt-5`. Worth a one-shot eval comparison before changing.

### Full-suite end-to-end nightly <!-- from: ~/.claude/sessions/PAM/2026-05-07.md -->
**Why:** the 2026-05-07 full run took ~2h wall-clock and ate one Claude rate-limit window. Nightly cron via the harness's `--start-from` would amortize that. Lower priority than the items above; only worth setting up if the full-suite number becomes a published metric.
