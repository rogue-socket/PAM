# Hybrid Retrieval Plan

> **Status — 2026-05-20: Phase A has shipped.** Embeddings (`pam/embeddings.py`, `BAAI/bge-small-en-v1.5`), the sqlite-vec `vec_nodes` table, the hybrid five-term score formula, and `pam migrate --backfill-embeddings` are all implemented. Phase B (LLM-at-ingest typed edges, the `MANAGES`/`MENTORS`/`COLLABORATES_WITH` vocabulary, and the edge `confidence` field) is **not** built. The body below is preserved as the original design proposal — for current behavior see `docs/MODULE_RETRIEVAL.md`, `docs/ARCHITECTURE.md`, and `config.py`. Some numeric placeholders below predate the shipped values: the live ranking weights are `WEIGHT_TEXT_RELEVANCE=0.30` / `WEIGHT_VEC_SIMILARITY=0.25` (the "existing `w_text = 0.45`" line was the pre-hybrid value, and the four weights now sum to 1.10).

Concrete proposal for the Phase-3 slice of [`docs/RETRIEVAL_RELATIONS_PLAN.md`](./RETRIEVAL_RELATIONS_PLAN.md): make graph-heavy questions answerable when keyword overlap with the corpus is weak. This is a doc to argue with — every numeric weight, model choice, and threshold is a candidate for revision before code.

Triggering gate: the IRL `colloquial_relationship` row scores 0/5 today on the FTS-only baseline (confirmed 2026-05-08, see `test_findings/2026-05-08_17-37-11_eval-full-pass.md`).

## Plain-language framing

PAM stores your personal notes. You ask questions later. Today, retrieval is keyword-matching: the question and the matching note have to share actual words.

Real notes and real questions don't share keywords.

Concrete example. You wrote:

> `"1:1 with Anya — discussed promotion timeline"`

Later you ask:

> `"who's my manager?"`

Zero words in common. FTS finds nothing. The LLM gets handed an empty memory and says `"I don't know from PAM memory."` This shape (colloquial-relationship phrasing in the corpus, role-word phrasing in the query) fails 5/5 today.

We add two channels:

1. **Embeddings** — a model converts notes and queries into vectors. Vectors that mean similar things land near each other. `"1:1 with Anya"` and `"who's my manager?"` are close in vector space even though they share no words. This is the wide net.
2. **LLM-at-ingest typed edges** — when you write `"1:1 with Anya"`, the LLM at ingest emits a structured fact: `Anya MANAGES user`. Now the relationship is queryable as a fact, not just searchable as text. Generalizes to any phrasing because the model handles meaning, not patterns. This is the precise tool.

Embeddings give recall. Typed edges give precision. They run together.

## Goals

- Lift across the expanded gate (see *Acceptance gates*): `colloquial_relationship` 0/5 → **≥60% on a 15–20 query version**, plus measurable lift on paraphrase / time-vague / entity-by-role rows added to the gate. `colloquial_relationship` is the *trigger* (demonstrated failure that justifies the work), not the only success criterion — embeddings + typed edges touch every query, so we measure lift across the eval, not just one row.
- No regression on `hard` (currently 192/192), `large` (currently 200/200), `detailed` (currently 96/110), or `regression` (currently 10/20 raw).
- Deterministic floor preserved: ingest and retrieve still work when neither the embedding model nor the LLM is available — same behavior as today.

## Non-goals

- Replacing FTS as the primary candidate channel. FTS stays; embeddings are additive.
- Adding a sidecar process (FAISS, Chroma, vector DB). Stays in-process / in-SQLite.
- Speculative new edge types beyond a controlled vocabulary. The model picks from a fixed list; it does not freeform new relations.
- Becoming a general graph DB query engine. The five edge families today plus a small expansion is the ceiling for v1.

## Architecture

### Channel 1 — embeddings

**Embedding model:** `BAAI/bge-small-en-v1.5`.

- 384 dimensions, ~33M parameters, runs on CPU in ~5ms/query.
- Local, no API key, MIT license.
- Strong on retrieval benchmarks at this size (MTEB top-tier for sub-100M models).
- Preserves the "deterministic offline floor" invariant — no network round-trip required.

| Alternative | Why not |
|---|---|
| `text-embedding-3-small` (OpenAI, 1536d) | Network dependency violates offline floor; cost ~$0.02/M tokens. Acceptable as a *secondary* path later, not as v1 default. |
| `all-MiniLM-L6-v2` (384d) | Older. bge-small outperforms it on MTEB. No reason to pick the older one. |
| `bge-large-en-v1.5` (1024d) | ~3x storage, ~5x latency, marginal quality gain at our scale. Reconsider if v1 hits a ceiling. |

**What gets embedded:** for each node, one vector over `title + content + summary + linked_entity_names`. One vector per node, recomputed on ingest, stored alongside the node. Queries get embedded at retrieval time.

**Entity records also get embedded** in Phase A — one vector per entity over its name + role/description + linked-node summaries. Reason: colloquial-role queries (`"who's my manager?"`) match on the *entity's* description more reliably than on any single node's content. Folding entity embeddings into Phase A (rather than a separate phase) keeps it as one coherent change: "embed everything that has searchable text".

### Channel 2 — LLM-at-ingest typed edges

When `pam/ingestion/llm.py` runs the existing summary/entity/edge-fact extraction call, we extend the same prompt to also emit typed edges from a controlled vocabulary.

**Controlled vocabulary (v1):** existing relations (`REFERS_TO`, `DERIVED_FROM`, `RELATED`, `CONTRADICTS`, `SUPERSEDES`) plus three new:

- `MANAGES(person → person)` — explicit reporting/management relationship
- `MENTORS(person → person)` — explicit mentoring/coaching relationship  
- `COLLABORATES_WITH(person ↔ person)` — frequent co-work indicator

The model picks from this list or returns nothing. It does not invent new relation kinds. New types added by the *team*, not by the model.

**Schema delta:** edges already carry a `weight` field. Add a `confidence ∈ [0, 1]` field on edges populated by LLM-at-ingest. Manual edges (from `feedback.py` operations) get `confidence = 1.0`. LLM-emitted edges get whatever the model returned, normalized.

**Prompt extension sketch:** add to existing ingest LLM prompt:
> *"If the note describes a typed relationship between two people from the entity list, return one of: `MANAGES(src, dst)`, `MENTORS(src, dst)`, `COLLABORATES_WITH(src, dst)`, with a confidence ∈ [0, 1]. Only emit when the relationship is explicit. Return nothing otherwise."*

**Why these three v1 types:** all three appear in the IRL corpus colloquial-relationship gate, all three are common in personal-work notes, all three have low ambiguity (manager-vs-not is a fact, not a judgment call). Borderline cases (`coffee with X` → friend? colleague?) deliberately not in v1.

### Storage

**`sqlite-vec`** — loadable SQLite extension, in-process, virtual table `vec_nodes(id INTEGER PRIMARY KEY, embedding FLOAT[384])`. Active maintenance (Mozilla / Alex Garcia). Successor to the now-unmaintained `sqlite-vss`.

| Alternative | Why not |
|---|---|
| sidecar (FAISS / Chroma / Qdrant) | Adds a process, a port, a deployment surface. We have ~10K nodes max in practice. Not worth it. |
| `sqlite-vss` | Unmaintained; sqlite-vec is the successor. |
| Roll our own with numpy + sqlite BLOBs | Works but reimplements ANN; sqlite-vec already does this. |

Loaded via `pam/db/schema.py` extension load. If the extension fails to load (different platform, missing binary), the system runs without vector retrieval — see *Deterministic fallback* below.

### Embedding lifecycle

Embeddings are properties of node content; when content changes, the vector must too. Four events to handle:

| Event | Behavior |
|---|---|
| Content / title / summary edit | Synchronous re-embed in the same write path. PAM's edit volume is low (`feedback.py` operations + supersede are the only edit paths) so the latency cost is real but small. |
| Supersede | Keep old embedding. Old node still exists at lower importance; vector is still valid for what it represents. |
| Archive | Keep embedding, filter at query time. Mirrors how archived nodes are filtered from FTS results today. |
| Delete | FK cascade `vec_nodes(id) → nodes(id)`. Vec row dies with the node. Schema-level, no app code. |

No background worker, no `needs_reembedding` flag, no queue. The "no sidecar" invariant applies here too. If the embedder is unavailable at edit time, the edit lands without re-embedding the vector and the next `pam migrate --backfill-embeddings` brings it back in sync.

### Score combination

In `pam/retrieval/ranker.py`, the existing per-node score is:

```
score = w_text·text_relevance + w_recency·recency + w_importance·importance + w_entity·entity_bonus
```

(weights from `config.py`, currently sum to 1.0, exposed in `score_components`).

Hybrid extension: add a fifth term.

```
score = w_text·text_relevance
      + w_vec·vector_similarity
      + w_recency·recency
      + w_importance·importance
      + w_entity·entity_bonus
```

`vector_similarity` = cosine between query embedding and node embedding, normalized to [0, 1]. Nodes that didn't make the FTS candidate set but score high on vector similarity get added to the candidate pool before ranking — vector retrieval is a *second recall channel*, not just a re-ranker on FTS hits.

**Weights:** `w_text` and `w_vec` are arbitrary at this stage. Existing `w_text = 0.45`. Initial proposal: `w_text = 0.30, w_vec = 0.25` (preserves the rest unchanged). These need tuning against the gate, not picking by intuition. Flagged as open in *Open questions*.

**Candidate pool:** today FTS returns up to 50 candidates before graph expansion. Hybrid: top 50 from FTS ∪ top 50 from vector similarity, deduplicated, then graph expansion runs as today.

### Edge-weight pipeline

LLM-at-ingest writes typed edges with `confidence ∈ [0, 1]`. Edge ranking already uses `edge weight`; we extend it:

```
final_edge_weight = base_weight · confidence
```

Manual edges (confidence = 1.0) unaffected. Lower-confidence LLM edges get proportionally damped in `relationship` ranking but stay in the graph as traversable.

## Deterministic fallback

PAM's hard requirement: ingest and retrieval work when LLMs and embedding models are unavailable. This plan must not break that.

**Tiered fallback table** — what works at each level:

| Available | Ingest | Retrieve |
|---|---|---|
| LLM + embeddings | typed edges + entity extraction + edge facts + node embeddings | FTS + vector + graph |
| Embeddings only | no typed edges; entity linker still runs deterministically | FTS + vector + graph |
| LLM only | typed edges + entity extraction + edge facts; no node embeddings | FTS + graph (today's behavior) |
| Neither | entity linker only (today's deterministic ingest); no typed edges | FTS + graph (today's behavior) |

**Telemetry:** when a tier degrades, write one event per ingest/query to `pam_log.jsonl` (`vector_unavailable`, `llm_unavailable`). Lets us measure how often the offline path fires in practice.

**No queueing:** if the embedding model isn't loaded at ingest, the note ingests without an embedding. No retroactive backfill queue. If the model becomes available later, a one-shot `pam migrate --backfill-embeddings` script can fill gaps. State stays in SQLite, not in a queue.

## Acceptance gates

Three roles, kept distinct.

**Trigger** — the demonstrated failure that justifies the work:
- IRL `colloquial_relationship`: **0/5 today**.

**Target** — what we're optimizing. Embeddings + typed edges touch the score formula for every query, so we measure lift across the eval, not just on the trigger row. Before Phase A starts, the eval gets thickened:
- `colloquial_relationship` expanded **5 → 15–20 queries**, mixing manager / mentor / collaborator phrasings and both directions (`"who's my manager"` *and* `"who reports to me"`). Target: **≥60%** on the larger set.
- Add **paraphrase** rows: queries whose answer note uses different vocabulary than the question (sweep `detailed` for candidates that already fail this way).
- Add **time-vague** rows: `"last quarter's launch correction"`, where FTS doesn't pick up the temporal phrasing.
- Add **entity-by-role** rows: `"the designer who reviewed X"`, where the note names the person but not the role.

Generation rule (per the matcher-as-triage-filter decision): real misses come from running the eval and having Claude confirm the answer is wrong. New rows are *authored* query/answer pairs; we do not pad the matcher.

**Guardrail** — what we can't break:
- `hard`: **192/192** maintained.
- `large`: **200/200** maintained.
- `detailed`: **≥96/110** maintained.
- `regression`: **≥10/20** raw maintained (real ≈95% post-triage).
- IRL non-trigger rows (the 42 queries outside `colloquial_relationship` / `paraphrase` / `time_vague` / `entity_by_role`): hit-count must not drop below today's baseline (~33/42 raw on the 2026-05-08 full run, before the eval was thickened). Re-baseline once the expanded eval has run on `main`.

Run order on each candidate change: `regression` → `irl` → `detailed` → `hard` → `large`. The first three are the meaningful signal; `hard` and `large` are regression confirmation.

## Phasing

**Phase A — embeddings only.** Add `sqlite-vec`, embed all nodes *and entity records* on ingest, hybrid score formula, run expanded gate. *Hypothesis: node + entity embeddings move the trigger row meaningfully and lift paraphrase / entity-by-role rows; time-vague is unlikely to move from embeddings alone.* If the expanded gate is met here, we stop and skip Phase B. Cheapest to ship; lowest design risk.

**Phase B — LLM-at-ingest typed edges.** Extend ingest prompt, add controlled vocab, write typed edges with confidence. Re-run gate. *Hypothesis: LLM edges close the remaining gap to ≥3/5 by making the manager/mentor relationship a queryable fact even when the embedding similarity is borderline.*

**Phase C (deferred — only if gate not met after A+B):** measure where the misses come from, propose Phase C from data. Might be re-ranking, might be query-side LLM expansion, might be more typed edge kinds. Don't pre-commit.

Order matters: A first because it's mechanical and gives a baseline. B second because it depends on prompt iteration and confidence calibration. Bundling both into one PR makes attribution impossible.

## Open questions / decisions deferred

1. **Four tunable numbers, all swept on the expanded gate:**
   - `w_text` — initial `0.30`
   - `w_vec` — initial `0.25`
   - candidate pool sizes — initial `50 ∪ 50` (FTS top-50 ∪ vector top-50, deduped, before graph expansion)
   - confidence threshold for typed-edge writes — initial `0.6` (below this: drop the edge; alternative is "write at any confidence, dampen in ranking")

   These are starting points, not settled values. Phase A logs all four with each retrieval; the sweep runs on the expanded gate and picks the configuration that maximizes lift without regressing the guardrail. No "initial proposal" treated as decided.
2. **Embedding-aware deduplication.** Today dedupe is by `content_hash`. Should two notes with high cosine similarity but different text get flagged as near-duplicates? Out of v1 scope but worth noting.

## Cross-references

- Strategy doc: [`docs/RETRIEVAL_RELATIONS_PLAN.md`](./RETRIEVAL_RELATIONS_PLAN.md) — this hybrid plan is the concrete Phase-3 proposal under that strategy.
- Architecture: [`docs/ARCHITECTURE.md`](./ARCHITECTURE.md) §Ranking Model — score formula extends the existing model rather than replacing it.
- Eval gate: [`test_findings/2026-05-08_17-37-11_eval-full-pass.md`](../test_findings/2026-05-08_17-37-11_eval-full-pass.md) — current 0/5 baseline on `colloquial_relationship`.
- Backlog item: `backlog.md` → "Hybrid retrieval: FTS + embeddings + write-time cue rules" — this doc is the planning-step deliverable.
