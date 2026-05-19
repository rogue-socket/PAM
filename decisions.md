# Decisions

Durable architectural and process decisions for PAM. Each entry is dated, leads with the decision, and carries a **Why:** line so future agents can judge edge cases.

The architecture *invariants* live in `CLAUDE.md` ("Core invariants — do not break"). This file captures judgment calls and methodology choices on top of those invariants — including any decision *not* to do something.

---

## 2026-05-06 — Deterministic fallback is a hard contract <!-- from: docs/AUDIT_2026-05-06.md -->
PAM ingest and query parsing must keep working when LLM SDKs are missing or fail. Don't add LLM-only code paths.
**Why:** lets PAM run from a clean clone with no API keys, supports reproducible offline evaluation, gives kayo an opt-out from external calls. Captured by `tests/test_deterministic_fallback.py`.
**How to apply:** any new ingest/query feature must pass through both the LLM path and a heuristic path. The "off" mode (`LLM_PROVIDER=claude_code` without `claude` on PATH) should produce sensible non-empty results.

## 2026-05-06 — Audit O5 closed without an explicit `LLM_PROVIDER="off"` mode <!-- from: docs/AUDIT_2026-05-06.md -->
The audit suggested an explicit `"off"` provider value; instead the contract is enforced by a deterministic-fallback test plus the existing fail-on-missing-SDK behavior.
**Why:** an `"off"` flag is redundant with the natural failure path; one fewer config knob to keep coherent.
**How to apply:** if a future requirement (e.g. air-gapped operation) needs it, add the flag — don't preemptively.

---

## 2026-05-07 — Matcher stays a triage filter, not the eval score <!-- from: ~/.claude/sessions/PAM/2026-05-07.md -->
The eval-harness substring matcher is a fast triage filter for surfacing candidate misses. The published quality score is `matcher hits + Claude-confirmed correct misses after manual triage`, not raw matcher hits.
**Why:** matcher false-negatives dominate (terse correct answers, plurals, prefixes). Chasing surface-form failures with more matcher rules is a treadmill; manual triage is fast and honest. Saved as feedback memory `feedback_eval_matcher_methodology.md`.
**How to apply:** when reading an eval log, expect the raw number to *under*-report quality. Don't propose more matcher rules; do propose ranker/retrieval changes that move *real* misses.

## 2026-05-07 — Flag arbitrary numeric values in plans <!-- from: ~/.claude/sessions/PAM/2026-05-07.md -->
Don't propose magic numbers in design plans. Either derive from existing constants in `config.py`, or call them arbitrary and explain the rough scale.
**Why:** confidently-stated arbitrary thresholds smuggle in hidden assumptions. User flagged this during O8 scoping. Saved as feedback memory `feedback_arbitrary_values.md`.
**How to apply:** when sizing buffers, weights, or thresholds in a proposal, name the existing constant or write "arbitrary, ~order of magnitude X."

## 2026-05-07 — O7b (broaden `_should_expand_related_concepts`) not pursued <!-- from: docs/AUDIT_2026-05-06.md -->
The expander already triggers RELATED-chain expansion on `intent == "reason"` and on `"RELATED" in relation_filters`. The audit asked to broaden this to influence/evolution/theme/gap shapes. Decision: don't.
**Why:** IRL baseline 2026-05-07 had multihop_2 5/5, multihop_3 3/3, multihop_4 1/1 — all at ceiling. No failing query points at the missing expansion. Broadening adds speculative candidates that risk displacing correct answers via ranking noise.
**How to apply:** revisit only when a concrete failing query traces to the missing RELATED expansion. Don't broaden speculatively.

## 2026-05-07 — O7c (true multi-hop traversal) deferred to roadmap <!-- from: docs/AUDIT_2026-05-06.md -->
The TODO at `pam/retrieval/graph_expander.py:258` calls for constrained multi-hop with path provenance. Decision: not audit-actionable; lives in the backlog as roadmap-level work.
**Why:** today's eval doesn't surface a failing query that obviously requires multi-hop graph traversal. The closest IRL miss (Q14, "what was Mira working on the same week as the auth fix push?") is a *temporal-proximity* problem, not a graph-traversal problem. Building speculatively before the failing-query case exists risks ranking-noise regressions.
**How to apply:** revisit when (a) the colloquial-relationship test corpus expansion (see `backlog.md`) produces concrete multi-hop failures, or (b) the hybrid-retrieval design pass concludes multi-hop is the right direction.

## 2026-05-07 — `MAX_GRAPH_DEPTH` removed (O7a) <!-- from: docs/AUDIT_2026-05-06.md -->
Defined in `config.py` but read nowhere. Removed.
**Why:** dead constants invite phantom assumptions ("we have a depth limit" — we don't; the expander uses a fixed traversal pattern). Removing surfaces the truth.
**How to apply:** when adding intent-driven traversal depth (eventual O7c work), introduce a new constant whose call site is the same commit as its definition.

## 2026-05-07 — SUPERSEDES write-path unification (O3) <!-- from: docs/AUDIT_2026-05-06.md -->
Both `pam.feedback.supersede` and the ingest-cue path now route through `pam.relations.apply_supersedes`. Replay is idempotent at the status level; importance dampening only fires on first edge creation. Telemetry log includes `source ∈ {"user", "ingest_cue"}` and `edge_created`.
**Why:** prior divergence (ingest path returned early on duplicate edges; feedback path always flipped status) meant a graph-reader couldn't tell which semantics had been applied. Single-source the contract.
**How to apply:** any new write path that creates a SUPERSEDES edge must call `apply_supersedes`. Don't reach into `create_edge` directly for this relation.

## 2026-05-07 — Lazy `check_database_health` warns, never raises (O2) <!-- from: docs/AUDIT_2026-05-06.md -->
`get_initialized_connection` runs the health check once per process per resolved DB path. Drift logs a `WARNING`; it does not raise. Auto-rebuild was deliberately not pursued.
**Why:** the eval and CLI paths must stay usable even if FTS drifts; failing-loud here would make a recoverable problem unrecoverable. Auto-rebuild was speculative until we see real drift in the wild.
**How to apply:** if drift is observed in production logs, the rebuild path can be added. Don't add it preemptively.

## 2026-05-07 — Per-call-site model defaults pinned in `config.py`
Four named constants (`LLM_INGESTION_MODEL`, `LLM_QUERY_PARSER_MODEL`, `LLM_CLAUDE_CODE_MODEL`, `CHAT_ANSWER_MODEL`). Existing env-var overrides (`ANTHROPIC_MODEL`, `CLAUDE_CODE_MODEL`) preserved.
**Why:** kayo evals shouldn't depend on env-var hygiene. The split (haiku for ingestion, sonnet for query parsing and answer) reflects the cost/quality tradeoff each call site needs.
**How to apply:** new LLM call sites should add a named constant to `config.py` rather than hard-coding a model ID at the call site or reading a fresh env var.

## 2026-05-18 — DERIVED_FROM is render-swapped, data convention untouched <!-- from: handoffs/2026-05-13.md /wrap, 2026-05-18 /start -->
PAM stores `DERIVED_FROM` as `source=parent_note (older) → target=derived_source (newer)`. Natural English `A DERIVED_FROM B` reads "A came from B" — the **opposite** of PAM's encoding. Fix is a render-time swap of source/target labels at every consumer that surfaces edges as titled text for an LLM: `scripts/run_copilot_cli_eval.py::_render_retrieval_context` and `pam/agent_interface.py::_plan_relationships`. The underlying edge convention (`pam/ingestion/pipeline.py:131-142`) is unchanged.
**Why:** changing the data convention would require migrating every consumer of `edge.source_id`/`edge.target_id` for this relation. The render-time swap is the cheap, contained fix. Discovered via a multi-hour debug on detailed-eval residuals #79/#80; eval-validated to 101/110 (vectors-on) when the swap is applied at render time. Without the swap, Claude mis-interprets DERIVED_FROM follow-on questions whenever edges render with titles instead of UUIDs.
**How to apply:** any new render path that turns edges into natural-English text must swap source/target when `relation == "DERIVED_FROM"`. If a future change reverses the underlying convention, audit every consumer that currently swaps and remove the workaround in lockstep — half-migrated state will flip the meaning back.

## 2026-05-19 — Eval matcher canonicalization: universal rules only, never per-query phrases <!-- from: IRL idx 17 fix discussion -->
`scripts/run_copilot_cli_eval.py::_canonicalize_match_text` is the matcher's pre-processing layer. It is allowed to grow with **universal language-level rules** (lowercase, markdown-emphasis strip, contraction expansion, number-unit whitespace collapse). It is **not** allowed to grow with rules that whitelist phrases for specific fixtures. Concretely: adding `("won't", "will not")` to `_CONTRACTIONS` is fine because the substitution is true in every English sentence. Adding `("didn't decide", "shadowed")` to a fixture's `expected_substrings` to absorb a single Claude wording is not — that's gaming the score for one query.
**Why:** the matcher's job is to be a triage filter, not the ground truth (see memory [[feedback_eval_matcher_methodology]]). Per-query phrase additions make the matcher number drift away from real recall — you stop noticing when Claude regresses because the matcher has been trained to pass that exact case. Universal canonicalization rules, in contrast, model how the language actually works and improve matcher accuracy uniformly across the corpus. The 2026-05-19 IRL idx 17 (Diego/auth wrong-premise) discussion locked this in: Claude said "Diego didn't decide... was shadowing you" against expected "did not decide / shadowed / mentoring"; the principled fix is contraction expansion in the canonicalizer, not adding "didn't decide" to query 17's substring list.
**How to apply:** new canonicalization rules go in `_canonicalize_match_text` (or its helpers like `_expand_contractions`). Before adding one, ask: "is this substitution true for *every* English sentence, regardless of fixture?" If yes, add it. If it's only true for the specific phrasing of one query, do not add it — either accept the miss as a known matcher-FN, or argue for a *broader* equivalence class first. Verb-tense stripping (`-ing`/`-ed`/`-s`) is borderline: tense often carries real semantic weight in PAM ("we shipped" ≠ "we are shipping"), so default to **no** unless a future case shows it's safe.

## 2026-05-19 — JSONL telemetry stays best-effort; not moved inside the txn <!-- from: backlog.md "Telemetry-in-txn", docs/DEPENDABILITY_PLAN.md Gap #2 -->
`_append_log` in `pam/feedback.py`, `pam/lifecycle.py`, and `pam/relations.py` keeps appending to `pam_log.jsonl` *after* the SQLite transaction commits, not inside it. The Phase 1 transaction work (commits `d620cfe`, `b2f0ed4`, `a9022dc`) was deliberately scoped to DB writes; the open question — "thread the log append into the txn success path, or lock in best-effort?" — is resolved as best-effort.
**Why:** `pam_log.jsonl` is telemetry, not an audit log. Coupling JSONL durability to SQLite transaction success would make a filesystem hiccup roll back legitimate DB writes, and "log line present ⇒ DB write happened" was never meant to be a contract — DEPENDABILITY_PLAN Gap #2 explicitly states "operators should not infer correctness from the presence or absence of a log line alone." Two failure modes both exist (DB-committed-but-log-missing, log-written-but-DB-rolled-back-via-context-manager-bug), and pretending one is fixed by reordering would obscure the real guidance: treat the log as debug telemetry and reach for SQLite itself when audit durability is needed.
**How to apply:** future write-path work should not thread `_append_log` calls inside `transaction()` blocks. If an audit-grade trail is ever required (e.g., regulatory provenance for a specific event class), persist it to a dedicated table inside the same transaction — do not repurpose the JSONL log. The DEPENDABILITY_PLAN Gap #2 stance ("keep describing `pam_log.jsonl` as telemetry only") is the durable rule.

## 2026-05-07 — Forward-looking design plans stay in `docs/`, not `prds/` <!-- from: /port-docs -->
`docs/DEPENDABILITY_PLAN.md` and `docs/RETRIEVAL_RELATIONS_PLAN.md` are alive, evolving roadmap docs.
**Why:** date-stamped `prds/` filenames are for snapshots. An evolving plan with a frozen-date filename misleads future agents about freshness.
**How to apply:** when a new design proposal is *point-in-time* (will be archived once decided), it goes in `prds/` with a timestamp. When it's a long-lived plan that gets edited as the architecture evolves, it lives in `docs/` with a topical filename.
