# Retrieval And Relations Plan

## Purpose

Track the path from the current relation-aware retrieval stack to the intended graph-native personal memory system.

This document is narrower than [DEPENDABILITY_PLAN.md](./DEPENDABILITY_PLAN.md). It focuses on how PAM should construct, traverse, rank, and expose graph relationships so the system can answer questions about influence, connection, evolution, themes, and gaps.

## Product Gap

The current system can already answer some explicit relation queries. That is not the same as handling the personal-memory use case well.

The target question families are:

- what influenced this idea
- how two workstreams connect
- how thinking evolved over time
- what themes are central
- what nearby topics are still underexplored

Those questions require more than relation-aware lookup. They require graph-native reasoning over stored memories.

## Current Baseline

The current retrieval stack already supports the following relation-aware behavior:

- FTS-first candidate retrieval with workspace scoping, time-window filtering, and keyword-overlap precision filtering before graph expansion
- deterministic parsing fallback when LLM parsing is unavailable, including relation-family inference for `SUPERSEDES`, `DERIVED_FROM`, `REFERS_TO`, `CONTRADICTS`, and `RELATED`
- relation-aware parsed query metadata: `relation_filters`, `relation_direction`, `answer_mode`, and anchor-term extraction
- requested-relation expansion before generic expansion, with direction-sensitive traversal for `incoming`, `outgoing`, and `both` queries
- relation-first ranking when `answer_mode=relationship` and specific `relation_filters` are present
- first-class `relationships` in `RetrievalResult`, while `conflicts` and `superseded` remain compatibility views over returned edges
- relation-aware human output in `cli.py query` and relation-aware context formatting in `pam.agent_interface.format_for_context_window`
- automated parser, expansion, ranking, CLI, agent, detailed-eval, large-eval, and hard-eval tests that exercise relation-heavy prompts

That is a real baseline. The repo is not starting from zero.

## Core Problems

### 1. Graph supply is still too thin

Current write-time relation creation is strongest for:

- `REFERS_TO` from entity linking
- `DERIVED_FROM` when a source is attached to a parent note
- `SUPERSEDES` via lifecycle and feedback operations

That is not enough to support graph-native answers about influence, themes, or adjacent topics. Retrieval cannot surface relations that ingest never wrote.

### 2. Candidate recall is still FTS-led

Graph reasoning usually begins after lexical candidate selection. That works when the right endpoints are textually obvious. It fails more often when:

- only one side of the relation is named clearly
- the answer is more visible in the edge or path than in a single node body
- the query is about themes or evolution rather than literal recall

### 3. Query understanding is still too narrow

The parser recognizes relation-heavy prompts better than before, but it still under-recognizes graph-native question shapes such as:

- influence
- evolution without explicit replacement language
- thematic synthesis
- adjacency or gap discovery

### 4. Ranking is edge-aware but not path-native

The current ranker can prioritize explicit edges. It cannot yet rank:

- multi-step explanation paths
- theme clusters
- adjacent-topic suggestions
- competing evolution chains

### 5. Output is graph-aware but not explanation-rich

`relationships` is now a first-class result field, which is the right direction. But the output contract still lacks richer explanation structures such as:

- winning paths
- why-this-answer labels
- graph-cluster summaries
- missing-edge diagnostics

## Design Principles

- keep retrieval operational without an LLM; deterministic fallback remains the minimum supported contract
- treat graph relationships as first-class memory objects, not just metadata on nodes
- preserve exact stored relation labels end to end
- prefer dependable write-time relation creation over speculative graph inflation
- improve answerability before adding a large ontology of new relation types
- make graph-native misses diagnosable rather than hiding them behind aggregate recall numbers
- avoid jumping to vector or cold-storage complexity before the core graph model is strong enough to justify it

## Workstreams

### 1. Graph Construction

Goal:

Write more of the graph PAM will later need.

Work:

- extend ingestion beyond entity references and source provenance
- capture stronger conceptual relatedness where rules are dependable
- preserve evidence for inferred links
- keep correction and evolution chains explicit

Success criteria:

- more personal-memory questions fail because retrieval is weak, not because the graph is absent

### 2. Query Understanding

Goal:

Recognize graph-native question classes explicitly.

Work:

- expand deterministic phrase coverage beyond replacement and provenance
- detect influence, evolution, themes, and gaps as distinct answer shapes
- improve anchor extraction for concept phrases and aliases
- normalize partial LLM metadata more aggressively without depending on it

Success criteria:

- graph-oriented prompts stop collapsing into generic node retrieval as often

### 3. Graph-Aware Candidate Selection

Goal:

Reduce dependence on raw lexical recall for graph-heavy questions.

Work:

- resolve anchors directly against nodes, entities, aliases, and concepts
- let strong anchors seed graph search before or alongside FTS
- use FTS as rescue recall rather than the only entry into the graph
- preserve workspace and time constraints end to end

Success criteria:

- graph-heavy prompts answer correctly even when exact lexical overlap is weak

### 4. Path-Aware Expansion And Ranking

Goal:

Return the right explanation, not only the right node.

Work:

- add constrained multi-hop traversal for explicit graph questions
- record how nodes were reached, not only which nodes were reached
- score edges, paths, and clusters in addition to nodes
- rank evolution chains, thematic centrality, and adjacency evidence explicitly

Success criteria:

- influence and evolution answers look like supported chains rather than bags of nearby memories

### 5. Output Contract For Agents And CLI

Goal:

Expose graph-native answers without making downstream consumers reconstruct the graph manually.

Work:

- keep JSON output relation-first and lossless
- add richer explanation payloads over time
- improve the human formatter for graph-style questions
- keep the agent context block compact but structurally faithful

Success criteria:

- human and agent callers can see the graph answer directly, not just infer it from ranked notes

### 6. Evaluation And Miss Diagnosis

Goal:

Judge graph-native quality with explicit automated gates.

Work:

- add maintained evaluation cases for influence, connection, evolution, themes, and gaps
- classify misses into parser, anchor-resolution, missing-edge, expansion, ranking, and rendering buckets
- keep detailed, large, and hard suites running after each substantial retrieval change

Success criteria:

- retrieval changes can be judged by failure mode rather than only by total score

## Recommended Execution Order

### Phase 1: Strengthen Ingest-Time Graph Supply

- harden existing provenance and supersession behaviors
- add dependable conceptual relation creation where rule support is strong
- keep relation evidence explicit

Expected outcome:

The graph contains more of the structure later queries need.

### Phase 2: Upgrade Query Planning

- recognize influence, evolution, theme, and gap question classes
- improve concept and alias anchors
- reduce overreliance on generic `answer_mode=relationship`

Expected outcome:

Graph-heavy prompts more often take a graph-aware path intentionally.

### Phase 3: Make Candidate Selection And Expansion More Graph-Native

- seed retrieval from anchors and graph neighborhoods when the query demands it
- add constrained multi-hop traversal
- keep lexical fallback for sparse-graph cases

Expected outcome:

Graph answers depend less on exact keyword overlap.

Concrete proposal under this phase: see [`HYBRID_RETRIEVAL_PLAN.md`](./HYBRID_RETRIEVAL_PLAN.md), which specifies the embedding model, vector storage, score combination, and LLM-at-ingest typed-edge extraction targeting the IRL `colloquial_relationship` 0/5 baseline.

### Phase 4: Make Ranking And Output Explanation-Rich

- score paths and clusters, not only nodes and explicit single edges
- expose explanation payloads to the CLI and agent interface
- add miss diagnostics and graph-native eval gates

Expected outcome:

The system can explain why an answer won and where it failed.

## Acceptance Metrics

The plan is succeeding when the following improve together:

- higher hit rates for graph-native question families in maintained eval suites
- fewer misses caused by absent edges for common personal-memory prompts
- fewer cases where the right nodes are present but the wrong relationship or path is surfaced
- clearer human and agent output for influence, evolution, and theme questions
- better miss categorization after retrieval changes

## Guardrails And Non-Goals

- do not claim graph-native reasoning quality from better lexical recall alone
- do not explode the ontology with many new relation types until write-time rules are dependable
- do not treat vector search or cold-storage tiers as the first fix for a weak graph
- do not rely on opaque model reasoning that cannot be grounded in stored evidence

Current automated floors cover the relation-aware baseline, not the full graph-native target:

- detailed suite: all 30 direct hits, at least 58 of 70 indirect hits, at least 19 relationship hits, and at least 88 overall hits
- large suite: at least 34 of 40 relationship hits and at least 92 percent overall score

## Explicit Non-Goals

- adding new edge types before current relation behavior is dependable
- replacing FTS-first retrieval with a vector-only design
- relying on an LLM-only planner for supported relation queries
- turning PAM into a general graph database query engine

## Immediate Next Steps

1. Re-run the detailed and large evaluation suites after each substantial retrieval change.
2. Bucket remaining relation misses into parser, expansion, ranking, output, or missing-edge failure.
3. Use that breakdown to choose the next smallest retrieval slice instead of broad heuristic changes.
