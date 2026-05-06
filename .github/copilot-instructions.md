# PAM Copilot Instructions

PAM is the memory layer for kayo. Use it through its stable CLI / agent boundary instead of reading or mutating the SQLite store directly.

## Setup

Install once per environment (any OS):

```
pip install -e .[llm,fuzzy]
```

This exposes the `pam` console script and pulls the optional Anthropic / OpenAI / rapidfuzz extras used for LLM enrichment and entity linking. PAM also runs without those extras — ingest and query degrade to deterministic paths.

## Memory Commands

- Start a session: `pam session start` (prints a session UUID).
- Add one memory per command: `pam add ...` (`--url`, `--file`, `--type note`, `--session`, `--at` are available).
- Query memory: `pam query "..." --json` for machine-readable output, plain `pam query "..."` for human output.
- Inspect a node or its edges: `pam show <id>` / `pam graph <id>`.

If `pam` is not on PATH (no editable install), `python cli.py ...` works from the repo root.

## Working Rules

- Prefer the PAM CLI or `pam.agent_interface` over direct DB access.
- Do not read or mutate `pam.db` directly.
- When answering a question that should come from PAM memory, query PAM first and base the answer on the returned result.
- If the retrieved PAM results do not support a confident answer, say so rather than guessing.
- When retrieval returns relationships, conflicts, superseded links, or sources, use those fields explicitly instead of flattening everything into a generic summary.

## Evaluation Rules

- For memory evaluations, keep the working directory at the PAM repo root so these instructions load and workspace scoping is stable.
- Use `PAM_DB_PATH` and `PAM_LOG_PATH` environment variables when an isolated evaluation database or log is needed.
- Do not inspect the evaluation fixture files to answer a memory question. Use PAM retrieval commands as the source of truth.
