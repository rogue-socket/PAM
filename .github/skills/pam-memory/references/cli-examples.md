# PAM CLI Examples

## Ingest Examples

```powershell
c:/workdir/PAM/.venv/Scripts/python.exe cli.py add "SQLite FTS5 supports full-text search over tokenized text." --type note
c:/workdir/PAM/.venv/Scripts/python.exe cli.py add --file article.txt
c:/workdir/PAM/.venv/Scripts/python.exe cli.py add --url "https://example.com/article"
```

## Query Examples

```powershell
c:/workdir/PAM/.venv/Scripts/python.exe cli.py query "What do we know about FTS5?" --json
c:/workdir/PAM/.venv/Scripts/python.exe cli.py query "Which notes mention retrieval quality?" --json
c:/workdir/PAM/.venv/Scripts/python.exe cli.py query "Summarize the stored thoughts about local-first systems" --json
```

## Output Checks

- `notes`: concise factual or reflective memories.
- `entities`: extracted named concepts or technologies.
- `sources`: article or URL-derived source nodes.
- `query_meta`: parsed keywords and retrieval metadata.
- Empty result sets are acceptable for unsupported queries, but repeated misses on obvious paraphrases indicate retrieval weakness.