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

## 2026-05-07 — Forward-looking design plans stay in `docs/`, not `prds/` <!-- from: /port-docs -->
`docs/DEPENDABILITY_PLAN.md` and `docs/RETRIEVAL_RELATIONS_PLAN.md` are alive, evolving roadmap docs.
**Why:** date-stamped `prds/` filenames are for snapshots. An evolving plan with a frozen-date filename misleads future agents about freshness.
**How to apply:** when a new design proposal is *point-in-time* (will be archived once decided), it goes in `prds/` with a timestamp. When it's a long-lived plan that gets edited as the architecture evolves, it lives in `docs/` with a topical filename.
