# Code Index

This document is a fast navigation map for the authored code. Use it to find the owning file first, then switch to the module docs for behavior details.

The most important stale-doc correction here is where to look for the graph-native transition. That work will not live in one magic file. It spans ingestion, retrieval, rendering, and evaluation.

## Fast Start

### Entry Points

- [../cli.py](../cli.py): human CLI, schema bootstrap, command wiring, and CLI-only JSON or human renderers.
- [../pam/agent_interface.py](../pam/agent_interface.py): stable agent-facing ingest and query boundary plus compact context rendering.
- [../pam/chat_agent.py](../pam/chat_agent.py): chat answer layer that turns PAM retrieval into grounded responses.
- [../scripts/run_copilot_cli_eval.py](../scripts/run_copilot_cli_eval.py): Copilot CLI evaluation harness that builds a fixed retrieval prompt and scores answers.
- [../scripts/run_all_copilot_evals.py](../scripts/run_all_copilot_evals.py): thin wrapper that runs the detailed, large, and hard eval suites and emits one combined JSON report.
- [../scripts/diag_relationship_misses.py](../scripts/diag_relationship_misses.py): diagnostic utility for analyzing relationship-query miss patterns in eval runs.

### Core Packages

- [../pam/db/schema.py](../pam/db/schema.py): connection setup, schema creation, migrations, workspace defaults, and health checks.
- [../pam/db/nodes.py](../pam/db/nodes.py): node CRUD, serialization, and query filters.
- [../pam/db/edges.py](../pam/db/edges.py): edge CRUD and relation lookup helpers.
- [../pam/db/fts.py](../pam/db/fts.py): safe FTS query shaping and candidate search.
- [../pam/db/transaction.py](../pam/db/transaction.py): SAVEPOINT-aware transaction context manager for atomic multi-step writes.
- [../pam/ingestion/pipeline.py](../pam/ingestion/pipeline.py): main ingest orchestration, dedupe, enrichment, and graph writes.
- [../pam/ingestion/extract.py](../pam/ingestion/extract.py): deterministic content extraction for notes, files, and URLs.
- [../pam/ingestion/entity_linker.py](../pam/ingestion/entity_linker.py): entity matching and draft entity creation.
- [../pam/retrieval/query_parser.py](../pam/retrieval/query_parser.py): deterministic and optional LLM-backed query parsing.
- [../pam/retrieval/search.py](../pam/retrieval/search.py): candidate retrieval, precision filtering, and query logging.
- [../pam/retrieval/graph_expander.py](../pam/retrieval/graph_expander.py): relation-aware graph traversal and edge fact collection.
- [../pam/retrieval/ranker.py](../pam/retrieval/ranker.py): node and relationship ranking, partitioning, and result shaping.
- [../pam/lifecycle.py](../pam/lifecycle.py): decay planning, archival, and restore operations.
- [../pam/feedback.py](../pam/feedback.py): upvote, downvote, pin, and supersede mutations.
- [../pam/embeddings.py](../pam/embeddings.py): query and node embedding for the vector-retrieval channel — lazy model load, vec-store writes, backfill.
- [../pam/telemetry.py](../pam/telemetry.py): shared best-effort JSONL log-append helper used by every log-emitting module.

## Graph-Native Implementation Hotspots

If the goal is to make PAM behave like a graph-native personal memory system rather than a note search tool, start here:

- [../pam/ingestion/pipeline.py](../pam/ingestion/pipeline.py): where richer graph construction must be orchestrated.
- [../pam/ingestion/entity_linker.py](../pam/ingestion/entity_linker.py): current relation supply starts here but is too entity-centric.
- [../pam/retrieval/query_parser.py](../pam/retrieval/query_parser.py): where graph-style question classes need stronger recognition.
- [../pam/retrieval/search.py](../pam/retrieval/search.py): where the current FTS-first bias lives.
- [../pam/retrieval/graph_expander.py](../pam/retrieval/graph_expander.py): where one-hop relation expansion must grow into more deliberate path exploration.
- [../pam/retrieval/ranker.py](../pam/retrieval/ranker.py): where node-first scoring must broaden into path, explanation, and cluster-aware scoring.
- [../pam/agent_interface.py](../pam/agent_interface.py): where richer retrieval payloads must still fit into a stable agent contract.
- [../cli.py](../cli.py): where graph-native answers must become understandable in human output.

### Tests By Concern

- [../tests/test_cli.py](../tests/test_cli.py): CLI formatting, command behavior, and the agent interface contract.
- [../tests/test_db.py](../tests/test_db.py): schema, node, edge, and FTS persistence behavior.
- [../tests/test_ingestion.py](../tests/test_ingestion.py): ingestion pipeline, dedupe, extraction, and entity linking.
- [../tests/test_retrieval.py](../tests/test_retrieval.py): query parsing, ranking, relation handling, and retrieval regressions.
- [../tests/test_relations.py](../tests/test_relations.py): dedicated relation regression coverage for formation, graph explanations, cross-discipline bridges, and evolution queries.
- [../tests/test_lifecycle.py](../tests/test_lifecycle.py): decay and archive behavior.
- [../tests/test_copilot_cli_eval.py](../tests/test_copilot_cli_eval.py): smoke and opt-in live tests for the Copilot CLI eval harness.
- [../tests/test_detailed_agent_eval.py](../tests/test_detailed_agent_eval.py): detailed authored eval corpus and query expectations.
- [../tests/test_large_agent_eval.py](../tests/test_large_agent_eval.py): large corpus evaluation coverage.
- [../tests/test_hard_agent_eval.py](../tests/test_hard_agent_eval.py): harder cross-memory eval scenarios.
- [../tests/hard_agent_eval_fixture.py](../tests/hard_agent_eval_fixture.py): generated fixture builder used by the hard eval suite.

## Output Shaping Surfaces

PAM keeps three similar renderers on purpose.

- [../cli.py](../cli.py): optimized for human-readable CLI output and JSON commands.
- [../pam/agent_interface.py](../pam/agent_interface.py): optimized for dense context-window packing for agent consumers.
- [../scripts/run_copilot_cli_eval.py](../scripts/run_copilot_cli_eval.py): optimized for stable eval prompts and raw-id debugging during score regressions.

Do not deduplicate these blindly. They overlap in structure, but they serve different callers and different output contracts.

## Cleanup Triage

- `.tmp_manual_cli/` is the first place to look when trimming non-product noise. Most of that tree is scratch or generated state.
- `.tmp_manual_cli/detailed_memory_eval/run_detailed_eval.py` is the important exception. Tests import it, so treat it like maintained source.
- [../scripts/run_all_copilot_evals.py](../scripts/run_all_copilot_evals.py) is intentionally thin. If the combined report is no longer needed, that wrapper is a safer cleanup target than the main ingest, retrieval, or CLI paths.
- [../review_inventory.txt](../review_inventory.txt) is a manual repository inventory snapshot. It is useful for cleanup triage, but it is not part of the product runtime.

## Related Docs

- [./ARCHITECTURE.md](./ARCHITECTURE.md): system boundaries, runtime model, and intended graph-native direction.
- [./MODULE_ROOT.md](./MODULE_ROOT.md), [./MODULE_DB.md](./MODULE_DB.md), [./MODULE_INGESTION.md](./MODULE_INGESTION.md), [./MODULE_RETRIEVAL.md](./MODULE_RETRIEVAL.md), [./MODULE_LIFECYCLE.md](./MODULE_LIFECYCLE.md), and [./MODULE_CLI.md](./MODULE_CLI.md): behavioral documentation for each maintained subsystem.
- [./TESTING.md](./TESTING.md): what each test and eval suite guarantees and what they still need to guarantee.
- [./REPOSITORY_ARTIFACTS.md](./REPOSITORY_ARTIFACTS.md): scratch, generated, and runtime artifacts outside the authored code path.