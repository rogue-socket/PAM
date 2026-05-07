# PAM Backlog

Open work that doesn't belong in the dated audit, isn't on a current sprint, but shouldn't get lost. Each item should name a *what* and a *why*, and link to related docs when useful. When an item gets picked up, move it into a session doc or audit and remove it from here.

## Eval / quality

### Expand the colloquial-relationship test corpus
**Why:** Q24 (`"who do I report to?"`) is the canonical example of a query class that the FTS-led baseline cannot answer — because the corpus uses *colloquial language* for the relationship (`"1:1 with Anya"`) instead of the keyword the user types (`"manager"`, `"report to"`). One example doesn't make a measurable suite. Before investing in semantic retrieval (`docs/RETRIEVAL_RELATIONS_PLAN.md` step toward graph-native) or write-time relation inference, we want enough Q24-shaped queries that we can measure whether a fix actually moves the number.

**Suggested additions to `tests/fixtures/irl_eval_corpus.json`:**
- `"1:1 with X"` → `"who's my manager?"` / `"who do I report to?"` / `"who's my skip-level?"`
- `"coffee chat with X"` / `"grabbed lunch with X"` → `"do I know X well?"`
- `"X assigned me to Y"` / `"X asked me to do Y"` → `"who's running Y?"` / `"what's my main project?"`
- `"shipped Y for X's team"` → `"what team am I on?"`
- `"X reviewed my PR"` → `"who reviews my code?"`

**Definition of done:** at least 5 colloquial-relationship queries in the IRL fixture, with corresponding corpus items that contain the relationship indirectly. Each should fail today's FTS baseline (zero retrieval recall) so the eval clearly distinguishes baseline from any future fix.

## Architecture / roadmap

### Hybrid retrieval: FTS + embeddings + write-time cue rules
**Why:** today's retrieval is FTS5 only. That's why Q24 fails — the answer note has zero token overlap with the question. Two complementary directions:

1. **Embeddings (vector search)** as a second recall channel. Encode each node's content + summary + linked entity names; encode the query the same way; surface top-k by cosine similarity in addition to FTS hits. Catches semantic paraphrase like `"1:1 with Anya"` ≈ `"who's my manager"`.
2. **Write-time cue rules for relationship inference.** When ingest sees `"1:1 with X"`, `"X reviewed my PR"`, etc., write a typed edge (`MANAGES`, `REVIEWED`, `COLLABORATES_WITH`) with a `confidence` field. Then graph queries can answer role questions without semantic retrieval.

These aren't either-or. Embeddings give recall on phrasing variation; cue rules give precision on high-confidence patterns and let the graph stay queryable. The architecture doc's intended-system framing already assumes both eventually.

**What this needs before code:**
- A short design doc (`docs/RETRIEVAL_HYBRID_PLAN.md` or extend `RETRIEVAL_RELATIONS_PLAN.md`) covering: embedding model + dimensions + storage (sqlite-vec? sqlite-vss? a sidecar?), how vector and FTS scores combine in the ranker, what cue patterns we trust enough to write edges from, how cue confidence flows into edge weight, and how the deterministic fallback contract holds when the embedding model is unavailable.
- A measurable evaluation gate — the colloquial-relationship suite above is the natural baseline.

**Definition of done (for the planning step, not the build):** a design doc the team can argue with. Build is downstream of agreement.

### True multi-hop graph traversal *(O7c from `docs/AUDIT_2026-05-06.md`)*
**Why:** `pam/retrieval/graph_expander.py:258` carries a TODO. Today's expander does a fixed traversal pattern, not depth-aware traversal driven by query intent. Roadmap-level. Today's eval does not yet present a failing query that obviously requires multi-hop, so this stays parked behind the colloquial-relationship suite producing harder cases.
