# PAM Module: CLI & Agent Interface
### `cli.py`, `pam/agent_interface.py`, `pam/chat_agent.py`
> Owner: Agent 5 | Depends on: `pam.db`, `pam.ingestion`, `pam.retrieval`, `pam.lifecycle`, `pam.feedback`, `config.py` | Depended on by: users and agent clients

---

## 1. Role

This layer owns PAM's user-facing entrypoints.

- `cli.py` is the human command surface
- `pam/agent_interface.py` is the stable agent-facing API for ingesting content, querying memory, and formatting retrieval results for a context window
- `pam/chat_agent.py` is the Copilot-backed answering layer that turns PAM retrieval into grounded chat responses

This layer wires together lower modules. It does not own ingestion policy, retrieval scoring, or storage details.

The stale-doc fix here is important: the CLI and agent surface should not be documented as neutral renderers over ranked notes. For the intended product, they are the place where graph-native answers become understandable to humans and agents.

---

## 2. Current CLI Surface

### 2.1 Shared setup and formatting

`cli.py` currently provides:

- `parse_datetime(value)`
- JSON helpers: `_node_to_dict()`, `_result_to_dict()`, `format_node_json()`, `format_nodes_json()`, `format_result_json()`
- human formatters: `format_node_human()`, `format_node_summary()`, `format_result_human()`
- `_resolve_add_input(text, url, filepath, node_type)`
- `main()`

The click group opens a DB connection with `get_connection()`, runs `initialize()`, stores the connection in `ctx.obj["conn"]`, and closes it with `ctx.call_on_close()`.

Current output behavior worth documenting:

- JSON retrieval output includes first-class `relationships` and `graph_explanations`
- human retrieval output renders a graph-answer summary section whenever retrieval returns first-class explanations, including bridge-based connection paths and simple evolution/theme/gap summaries, and falls back to the older relationship-first branch only when those explanations are absent

### 2.2 Commands

The live command set is:

- `pam add`
- `pam session start`
- `pam query`
- `pam chat`
- `pam upvote`
- `pam downvote`
- `pam pin`
- `pam supersede`
- `pam decay`
- `pam unarchive`
- `pam show`
- `pam list`
- `pam graph`
- `pam migrate`
- `pam stats`

Important command behavior:

- `add` requires exactly one of plain text, `--url`, or `--file`
- `add` rejects `--type` when the input is a URL or file
- `add` passes the shared CLI connection into `ingest()`
- `query` calls `retrieve(query_text, top_k=top_k)` and optionally renders JSON
- `chat` grounds a Copilot answer on `query_for_agent()` plus `format_for_context_window()` and can optionally print the retrieved PAM context
- `list` filters by `type`, `status`, `since`, and `limit`
- `graph` prints both outgoing and incoming edges with fact text when available
- `migrate` just re-runs `initialize()`
- `stats` reports counts by node type, status, edge relation, and FTS entries

---

## 3. Current Agent Surface

`pam/agent_interface.py` exports:

- `AgentIngestResult`
- `ingest_for_agent(raw_value, *, kind=None, session_id=None, valid_at=None, workspace_id=None, parent_note_id=None)`
- `query_for_agent(raw_query, top_k=None, workspace_id=None)`
- `format_for_context_window(result)`

The live ingest result contract is minimal:

```python
@dataclass
class AgentIngestResult:
    node_id: str
```

Important current behavior:

- `ingest_for_agent()` supports `workspace_id` and `parent_note_id`
- `kind="source"` forces `input_type="document"` and `node_type="source"`
- `kind="event"` forces `input_type="task"` and `node_type="event"`
- when `kind` is empty or `link` and the value looks like an `http`, `https`, or `file` URL, agent ingest routes to source ingestion automatically
- everything else defaults to note ingestion
- `query_for_agent()` forwards `workspace_id` to retrieval when present and normalizes path-like values to strings

---

## 4. Chat Answer Surface

`pam/chat_agent.py` exports:

- `ChatAgentError`
- `ChatResponse`
- `answer_with_pam(raw_query, *, model=..., top_k=..., workspace_id=None)`
- `build_chat_prompt(raw_query, retrieved_context)`
- `retrieve_context_for_chat(raw_query, *, top_k, workspace_id=None)`

Important current behavior:

- chat grounding reuses the stable agent-facing retrieval path rather than inventing a separate search stack
- the retrieved context is rendered through `format_for_context_window()` so the conversational surface stays aligned with the agent contract
- Copilot CLI discovery is lazy, so importing the module does not fail on machines that only use ingest and retrieval
- `answer_with_pam()` returns both the final answer and the retrieved context so CLI callers can expose the grounding when debugging memory quality
- missing Copilot CLI binaries, subprocess failures, and timeouts raise `ChatAgentError`

---

## 5. What This Surface Needs To Do For Graph-Native Memory

The CLI and agent layer is where graph-native retrieval becomes legible. If the renderer collapses graph answers back into a flat note list, the product still feels like search even if the retriever improved.

### 5.1 Human output requirements

For the personal-memory use case, human-facing answers should increasingly support:

- relationship-first rendering for explicit graph questions
- short explanation chains for influence and evolution prompts
- clearer provenance display when a note is backed by sources
- theme summaries that identify the most central connected concepts
- adjacent-topic suggestions that show why the topic is nearby but underexplored

### 5.2 Agent output requirements

Agent-facing output should increasingly surface:

- the winning nodes and the winning edges or paths
- explanation metadata without forcing the downstream agent to infer structure from prose alone
- enough graph context that grounded answer generation stays faithful to stored evidence

### 5.3 Chat requirements

The chat surface should remain grounded in PAM retrieval.

For graph-native questions, that means `answer_with_pam()` should benefit from richer structured retrieval context rather than asking the answering model to invent the graph from a list of loosely related notes.

---

## 6. Context Window Formatting

`format_for_context_window()` is a concrete API contract, not just a presentation helper.

Important current behavior:

- the output starts and ends with `---` section dividers
- graph explanations are shown first when the retrieval result includes non-empty `result.graph_explanations`
- relationship hits are still shown first as a fallback only when the retrieval result is in relationship-answer mode, explicit `result.relationships` were returned, and no graph explanations are present
- multi-segment graph explanations can now preserve explicit per-segment labels so bridge concepts remain readable even when the bridge node itself is not surfaced as a result node
- the formatter emits sections for events, notes, sources, entities, conflicts, superseded pairs, and relationships when present
- the output is capped by `MAX_CONTEXT_CHARS`, currently `4000`
- when the rendered payload exceeds that budget, the truncator preserves the no-dangling-reference invariant: a relationship/conflict/graph-answer line is kept only when every node it references also has its line present in the output. Referenced node lines are admitted before unreferenced ones, and ref lines whose endpoints are evicted are dropped; the output ends with `[truncated]`.

If graph explanations are absent and relationship-answer mode is requested but no explicit relationship hits are present, the relationships section falls back to its normal later position after the node sections.

This truncation behavior matters to agent callers that rely on a bounded context block.

For the intended implementation, the formatter will likely need to accommodate more structured evidence, such as explanation paths, while still preserving bounded output.

---

## 7. Interface Design Rules

- the CLI should remain a thin orchestration layer
- `add` must keep the exactly-one-of-text-url-file invariant
- CLI and agent formatting must continue to surface first-class graph structure from retrieval results rather than reconstructing it ad hoc
- agent callers should use `query_for_agent()` and `ingest_for_agent()` instead of reaching directly into deeper modules unless they need lower-level control
- chat answers should stay grounded in PAM retrieval rather than bypassing memory and answering from outside context
- graph-native improvements should appear first as richer retrieval payloads and renderers, not as ad hoc CLI-only logic

---

## 8. Practical Near-Term Improvements

The docs should be explicit about where this layer is weak today.

- `show` does not yet summarize provenance, supersession, or idea-chain context directly
- graph-answer summaries are now present, but deeper multi-hop chains and richer diagnostics still need stronger retrieval payloads before the CLI can expose them well
- agent formatting is already a stronger surface than the plain human formatter and should stay the preferred integration boundary while retrieval becomes more graph-native
