---
name: pam-memory
description: 'Use for PAM memory ingestion and retrieval through the repository CLI. Trigger when asked to add memories, ingest notes or articles, query stored context, inspect retrieved memories, or validate PAM search output with Copilot.'
argument-hint: 'Describe what to ingest or what memory question to ask PAM.'
user-invocable: true
---

# PAM Memory Skill

Use this skill when you need to store or retrieve local memory from this repository's PAM database through the CLI-first workflow.

## When To Use

- Add a note, event, article, URL, or file into PAM.
- Start a session and group related memories.
- Query PAM before answering a task that may depend on prior stored context.
- Validate retrieval quality with explicit sample queries.

## Command Surface

Run the repository CLI with the configured workspace interpreter:

```powershell
c:/workdir/PAM/.venv/Scripts/python.exe cli.py session start
c:/workdir/PAM/.venv/Scripts/python.exe cli.py add "Remember this" --type note
c:/workdir/PAM/.venv/Scripts/python.exe cli.py add --file path/to/article.txt
c:/workdir/PAM/.venv/Scripts/python.exe cli.py query "what do we know about X?" --json
```

## Procedure

1. Start a session with `cli.py session start` when a batch of memories belongs together.
2. Ingest one memory per command with `cli.py add`.
3. Use plain text with `--type note` for thoughts and durable notes.
4. Use `--file` for article or document content.
5. Use `--url` for source links.
6. Query with `cli.py query ... --json` when machine-readable output is needed.
7. When checking quality, compare returned notes, entities, sources, conflicts, superseded links, and query metadata.

## Validation Guidance

- Prefer a mixed corpus: article text, concise factual notes, and short reflective thoughts.
- Ask both direct lookup questions and paraphrased questions.
- Include at least a few relationship-oriented queries, such as timeline, source, contradiction, or theme queries.

See [CLI examples](./references/cli-examples.md) for reusable command patterns.