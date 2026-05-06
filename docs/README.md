# PAM Documentation

This folder is the source-of-truth documentation set for the PAM repository.

PAM is no longer documented as "FTS plus some graph expansion" and left at that. The code today is an FTS-led, relation-aware baseline. The intended product for this repository is a graph-native personal agent memory system that can explain idea evolution, architectural relationships, themes, and gaps in what the user has explored.

The documentation now uses two labels consistently:

- Current baseline: behavior that exists in the repository today.
- Intended implementation: behavior PAM should grow into for the personal-memory use case.

That distinction matters because the docs should be honest about the current code while still answering the harder design question: how should this repo implement graph-native personal memory reasoning without drifting into vague product language.

## Product Thesis

PAM should help a personal agent answer questions such as:

- what influenced this idea
- how two parts of my work connect
- how my thinking evolved over time
- what themes are central in my work
- what nearby topics I have not explored yet

That means graph structure is the primary memory model. Lexical retrieval, optional model-assisted parsing, and any future embedding or vector layer are support mechanisms for finding and ranking the right graph evidence, not substitutes for the graph.

## Documentation Goals

- Explain the current implementation accurately.
- Document the intended graph-native direction explicitly enough to drive implementation work.
- Show how ingestion, retrieval, lifecycle, feedback, and CLI surfaces should support personal-memory reasoning.
- Map tests and evaluations to the behaviors that matter for this use case.
- Keep a coverage matrix so no maintained repository artifact becomes undocumented.

## Reading Order

1. [ARCHITECTURE.md](./ARCHITECTURE.md)
2. [RETRIEVAL_RELATIONS_PLAN.md](./RETRIEVAL_RELATIONS_PLAN.md)
3. [FLOWS.md](./FLOWS.md)
4. [MODULE_RETRIEVAL.md](./MODULE_RETRIEVAL.md)
5. [MODULE_INGESTION.md](./MODULE_INGESTION.md)
6. [MODULE_CLI.md](./MODULE_CLI.md)
7. [MODULE_LIFECYCLE.md](./MODULE_LIFECYCLE.md)
8. [MODULE_DB.md](./MODULE_DB.md)
9. [MODULE_ROOT.md](./MODULE_ROOT.md)
10. [TESTING.md](./TESTING.md)
11. [EXPLORATORY_EVALUATION.md](./EXPLORATORY_EVALUATION.md)
12. [CODE_INDEX.md](./CODE_INDEX.md)
13. [REPOSITORY_ARTIFACTS.md](./REPOSITORY_ARTIFACTS.md)
14. [DEPENDABILITY_PLAN.md](./DEPENDABILITY_PLAN.md)
15. [DOCUMENTATION_COVERAGE.md](./DOCUMENTATION_COVERAGE.md)

## Document Set

This overlaps intentionally with the reading order above: the list below is for role and scope, not sequence.

- [ARCHITECTURE.md](./ARCHITECTURE.md): product thesis, current runtime model, and the target graph-native architecture for personal memory.
- [RETRIEVAL_RELATIONS_PLAN.md](./RETRIEVAL_RELATIONS_PLAN.md): concrete implementation roadmap for moving from relation-aware retrieval to graph-native reasoning.
- [FLOWS.md](./FLOWS.md): current and target ingestion, retrieval, lifecycle, CLI, and agent flows.
- [MODULE_RETRIEVAL.md](./MODULE_RETRIEVAL.md): current query parsing, search, expansion, and ranking behavior plus the required retrieval redesign.
- [MODULE_INGESTION.md](./MODULE_INGESTION.md): current write path and the graph-construction work it still needs to do.
- [MODULE_CLI.md](./MODULE_CLI.md): human and agent-facing surfaces, with emphasis on how graph answers should be exposed.
- [MODULE_LIFECYCLE.md](./MODULE_LIFECYCLE.md): maintenance rules for preserving memory evolution, replacement, and long-term relevance.
- [MODULE_DB.md](./MODULE_DB.md): persistence layer, graph storage primitives, and the storage implications of richer reasoning.
- [MODULE_ROOT.md](./MODULE_ROOT.md): top-level modules and configuration surfaces that shape the system.
- [TESTING.md](./TESTING.md): current coverage and the missing graph-native evaluation gates.
- [EXPLORATORY_EVALUATION.md](./EXPLORATORY_EVALUATION.md): what current evaluation actually proves and what it does not yet prove.
- [CODE_INDEX.md](./CODE_INDEX.md): fast code navigation, especially for graph-construction and graph-reasoning work.
- [REPOSITORY_ARTIFACTS.md](./REPOSITORY_ARTIFACTS.md): support files, runtime state, and evaluation artifacts.
- [DEPENDABILITY_PLAN.md](./DEPENDABILITY_PLAN.md): dependability posture for a graph-native memory system, not only a local note store.
- [DOCUMENTATION_COVERAGE.md](./DOCUMENTATION_COVERAGE.md): file-to-document mapping for full coverage.

## Coverage Rule

The phrase "100% documentation coverage" in this repository means:

- every maintained source file is described in at least one module or architecture document
- every test file and fixture is described in the testing document
- every maintained support file and every generated or runtime artifact class the repo intentionally tracks is described in the repository artifacts document
- docs that discuss future behavior distinguish intended implementation from current code
- the coverage matrix explicitly lists where each artifact is documented

## Maintenance Rule

When a file is added, renamed, removed, or materially changes behavior:

1. Update the relevant module document.
2. Update [TESTING.md](./TESTING.md) or [REPOSITORY_ARTIFACTS.md](./REPOSITORY_ARTIFACTS.md) if the change affects tests or support artifacts.
3. Update [DOCUMENTATION_COVERAGE.md](./DOCUMENTATION_COVERAGE.md).
4. If the change moves PAM closer to or further from the graph-native architecture, update the current-versus-intended wording where needed.
