# PAM Eval Suites — Side-by-Side

PAM has five end-to-end eval corpora. Each tests a different thing. This doc is the cheat-sheet for picking the right one and understanding what a passing/failing score means in each.

| Suite | Corpus | Queries | Source | Repetition | Tests for |
|-------|--------|---------|--------|------------|-----------|
| **detailed** | 55 | 110 | Handcrafted (one rich domain) | LOW | Natural-language **variety + paraphrase robustness** |
| **hard** | 96 | 192 | Programmatic × 16 scenarios | HIGH | **Consistency** of retrieval across many similar shapes |
| **large** | 100 | 200 | Programmatic × 20 scenarios | HIGH | **Scale + consistency** (broader, shallower than hard) |
| **regression** | 27 | 20 | Hand-curated about PAM itself | LOW | **Dogfooding** — PAM should explain its own design |
| **irl** | 31 | 68 | Hand-curated, messy real-world | LOW | **Real-world mess** — vague / typo / multi-hop / wrong-premise / colloquial-relationship / paraphrase / demanding / time-relative / time-vague / entity-by-role / out-of-blue |

All five are runnable end-to-end via `scripts/run_copilot_cli_eval.py --suite <name>` (since 2026-05-06).

## Pick by intent

| If you want to know… | Run |
|-----------------------|-----|
| "Does basic retrieval work on natural language?" | `detailed` |
| "Is retrieval consistent across many similar entities?" | `hard` |
| "Can PAM explain its own design?" | `regression` |
| "How does PAM behave when queries are messy?" (recommended for kayo) | `irl` |
| "Statistical confidence over hundreds of queries" | `large` |

For day-to-day development, **`irl` gives the highest signal per query** — every miss maps directly to a fix. The templated `hard` and `large` suites are statistical (the same question template hit 16-20 times); they confirm consistency but don't expose new failure modes once `hard` has been run.

## Suite-by-suite detail

### detailed (55 / 110)

**Domain**: coastal-monitoring field operations — sensors, gulls, pilots, drones, OCR vendors, planning. One rich narrative across 55 corpus items, 11 each of `note`/`event`/`source`/URL.

**Queries**: 110 unique. Mix of `lookup` (40), `paraphrase` (28), `relationship` (26), `timeline` (11), `negative` (5). 32 direct + 78 indirect. Only 2 SUPERSEDES pairs (lightweight evolution).

**What a miss tells you**: the query is genuinely ambiguous in natural language, OR the matcher's expected substring is unrealistically verbose for what the model returns.

**Asserted floor (deterministic-only)**: ≥88/110 (≥80%), with 32 direct + ≥58 indirect + ≥7 timeline + ≥19 relationship.

**Examples**:
- "What maintenance rhythm was proposed for dirty antennas after gull season?" → "every second tuesday"
- "After 2026-04-10, what change and fix defined launch week?" → "april 26", "manifest-revision invalidation patch"
- "What did users trust before probabilities?" → "users trusted arrows before they trusted probabilities"

### hard (96 / 192)

**Domain**: 16 fictional storage / routing systems with templated stories: alias (HLD, HLT, ...), issue, metric_action + metric_value, residency, approver, drill, workaround, incident_site. Each scenario produces 6 corpus items × 12 queries.

**Queries**: heavily templated. Same 12 questions per scenario:
- "Who approved the revised X plan?"
- "What target did X move to after the revision?"
- "Where must X snapshots stay before redaction?"
- "What changed handoff speed for X after Y?"
- "What source was derived from the revised X plan?"
- "Between DATE and DATE, what target did X move to?"
- 2 negatives per scenario (orchard pruning ladders, etc.)

16 SUPERSEDES pairs (one per scenario).

**What a miss tells you**: a retrieval pattern broke — and because each pattern is hit 16 times, you'll see it cluster (e.g. all "revised target" queries fail or all succeed).

**Asserted floor**: ≥181/192 (≥94%) split as ≥60 lookup, ≥30 paraphrase, ≥30 relationship, ≥30 timeline, ≥31 negative.

### large (100 / 200)

**Domain**: 20 fictional rollout systems (Aurora Ledger, Beacon Routing, Cascade Forms, ...). Same template-engine flavor as `hard`, slightly different question set per scenario (10 questions × 20 scenarios). 20 SUPERSEDES pairs.

**Queries**: ≥76 lookup, ≥36 paraphrase, ≥34 relationship, ≥16 timeline, ≥19 negative. Floor ≥181/200 (≥90.5%).

**What a miss tells you**: same as `hard` — a retrieval pattern broke. Heavily redundant with `hard` — if `hard` passes, `large` typically does too.

**Verdict**: if you had to drop one, drop `large`. It exists for statistical confidence at scale.

### regression (27 / 20)

**Domain**: PAM itself. 7 article files about PAM design (temporal semantics, FTS limits, ranking weights, edge facts, local-first), 12 short factual notes, 8 stream-of-consciousness "thoughts". This is dogfooded technical doc.

**Queries**: 20 hand-written, all `lookup`. Most have very specific verbose `expected_substrings` (literal note text, not paraphrases). 1 negative.

**What a miss tells you**: either (a) a retrieval regression, (b) the matcher's verbose expected text is unrealistic for the model's natural phrasing, or (c) the LLM picked the wrong memory from a multi-memory result. The 2026-05-06 run had 9 of 12 misses turn out to be matcher false-negatives — the model was paraphrasing correctly.

**Examples**:
- "What is the stable machine-readable interface for Copilot callers?" → "The --json flag is..."
- "How do valid_at and created_at differ?" → "valid_at expresses real-world time of validity"
- "Which ranking signals carry the highest weight?" → "text relevance and recency tied" (`config.py` has `WEIGHT_TEXT_RELEVANCE = 0.30` tied with `WEIGHT_RECENCY = 0.30`)
- "What limit is used before graph expansion?" → "FTS candidate limit is 50"

### irl (31 / 68) — recommended for kayo

**Domain**: a working engineer's mid-month memory state. 5 themed threads:
- Auth bug investigation with corrected diagnosis (JWT theory → SameSite/Safari ITP correction, 1 SUPERSEDES pair)
- Code review thread (Rakhi's cache-locking PRs)
- RFC thread (Postgres → ClickHouse migration with pushback, compromise, revised estimate, decision)
- Stripe sandbox debugging
- Mentoring chain (Anya 1:1 → Diego shadowing → readiness assessment)

Plus 5 personal opinions, 3 stream-of-consciousness items.

**Queries**: 68 unique, organized by realistic-mess category:

| Category | Count | Example |
|----------|-------|---------|
| `colloquial_relationship` | 16 | "who do I report to?" |
| `wrong_premise` | 6 | "when I cancelled the ClickHouse migration, what was the alternative?" (didn't cancel) |
| `casual` | 5 | "rakhi pr stuff" |
| `multihop_2` | 5 | "after we switched off pip-tools, what package manager did I land on?" |
| `multihop_3` | 5 | "Mira's compromise on the event store — when was the final decision made?" |
| `vague` | 5 | "what was that auth thing again?" |
| `demanding` | 4 | "list everyone whose PR I reviewed in April and what each contained" |
| `negative` | 4 | "what did Tom say about the kubernetes upgrade?" |
| `paraphrase` | 4 | "what's the auth bug rooted in Apple's privacy crackdown?" |
| `entity_by_role` | 3 | "the person who pushed back on the database migration" |
| `time_relative` | 3 | "what did I do last week?" |
| `time_vague` | 3 | "the auth thing from last month" |
| `partial_id` | 2 | "PR 441 status" |
| `multihop_4` | 1 | "based on my preference for pytest-xdist, what would I likely think about pytest-parallel?" |
| `out_of_blue` | 1 | "favorite coffee in bergen?" |
| `typo` | 1 | "wat did i fix on apr 15" |

**What a miss tells you**: surgical. Each category isolates a different failure mode:
- A `wrong_premise` miss = answer prompt too conservative (forces NO_ANSWER instead of pushback)
- A `time_relative` miss with 0 retrieved nodes = retrieval needs to bypass FTS when `intent=timeline` and time_range is set
- A `demanding` miss with the right context = answer prompt's NO_ANSWER rule fires too eagerly
- An `out_of_blue` miss = colloquial entity-type queries need synonym expansion

**Run**:
```bash
python scripts/run_copilot_cli_eval.py --suite irl --backend claude \
  --batch-size 10 --include-misses
```

The 2026-05-06 run scored 33/38 = 86.8% on the original 38-query corpus (all 5 misses real, no matcher false-negatives). The corpus has since grown to 68 queries, adding the `colloquial_relationship`, `paraphrase`, `time_vague`, and `entity_by_role` categories. See `docs/EVAL_RESULTS_2026-05-06.md` for the original breakdown and `test_findings/` for later runs.

## Adding a new suite

1. Create a fixture loader at `tests/<name>_eval_fixture.py` exposing a callable that returns `{"corpus": [...], "queries": [...], "supersedes": [...]}`.
2. Add the fixture JSON under `tests/fixtures/` (or build the dict in code).
3. Register in `scripts/run_copilot_cli_eval.py:SUITE_SPECS`.

Corpus item shape:
```python
{"key": "unique_id",
 "at": "2026-04-21T12:00:00+00:00",
 "session": "any-string",
 "ingest_kind": "note" | "event" | "file" | "url",
 "text": "...",
 "filename": "..." }     # required only for url; optional for file
```

Query shape:
```python
{"query": "...",
 "query_type": "any-string",      # used as a bucket label
 "kind": "direct" | "indirect",   # informational
 "expected_substrings": [...]     # OR
 "expect_empty": True}            # for negatives
```

Supersedes: `[(old_key, new_key), ...]` — applied via `feedback.supersede()` after ingest.
