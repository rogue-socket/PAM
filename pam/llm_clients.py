"""Shared LLM client primitives.

Single source of truth for `LLMUnavailableError` (previously duplicated in
`pam.ingestion.llm` and `pam.retrieval.query_parser` — distinct classes that
did not catch each other) and the `claude_code` provider that shells out to
the Claude Code CLI for environments without an Anthropic/OpenAI API key.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from functools import lru_cache


class LLMUnavailableError(RuntimeError):
    """Raised when the configured LLM provider cannot be reached locally."""


@lru_cache(maxsize=1)
def _resolve_claude_cli() -> str:
    """Locate the `claude` CLI on PATH. Cached but cheap to re-invoke."""
    on_path = shutil.which("claude")
    if not on_path:
        raise LLMUnavailableError(
            "Claude Code CLI (`claude`) not found on PATH. "
            "Install Claude Code or set PAM_LLM_PROVIDER to a different provider."
        )
    return on_path


def call_claude_code(prompt: str, *, model: str | None = None, timeout: int = 60) -> str:
    """Run a one-shot prompt through the Claude Code CLI and return stdout.

    Stdin is closed (DEVNULL) so the CLI does not pick up unrelated context.
    Raises LLMUnavailableError on missing binary, non-zero exit, or timeout —
    callers (`_safe_llm_text`, query parser) expect that contract for graceful
    deterministic fallback.
    """
    binary = _resolve_claude_cli()

    command = [binary, "-p", prompt, "--output-format", "text"]
    if model:
        command.extend(["--model", model])

    try:
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=timeout,
            check=False,
            env=os.environ.copy(),
        )
    except subprocess.TimeoutExpired as exc:
        raise LLMUnavailableError(f"claude CLI timed out after {timeout}s") from exc
    except FileNotFoundError as exc:
        # Race: PATH had `claude` at lookup time but it disappeared between
        # cache hit and execve. Treat as unavailable.
        raise LLMUnavailableError("claude CLI binary disappeared between lookup and execution") from exc

    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        stdout = completed.stdout.decode("utf-8", errors="replace").strip()
        raise LLMUnavailableError(stderr or stdout or f"claude exited with code {completed.returncode}")

    return completed.stdout.decode("utf-8", errors="replace").strip()


_FENCE_PATTERNS = (
    "```json\n",
    "```JSON\n",
    "```\n",
)


def unwrap_json_response(text: str) -> str:
    """Best-effort: strip markdown fences and prose around a JSON payload.

    Some CLI-routed providers (notably the Claude Code CLI) wrap structured
    responses in ```json ... ``` or precede them with conversational prose,
    even when the prompt asks for bare JSON. This helper returns the first
    balanced JSON object or array it can find. If no recognizable JSON is
    present, returns the input stripped — letting the caller's json.loads
    raise its usual error.
    """
    if not text:
        return text

    stripped = text.strip()

    for fence in _FENCE_PATTERNS:
        if stripped.startswith(fence):
            stripped = stripped[len(fence):]
            if stripped.endswith("```"):
                stripped = stripped[: -len("```")]
            return stripped.strip()

    if stripped and stripped[0] in "{[":
        return stripped

    # Prose preamble: pick whichever opener appears first.
    obj_start = stripped.find("{")
    arr_start = stripped.find("[")
    candidates = [(pos, opener, closer) for pos, opener, closer in (
        (obj_start, "{", "}"),
        (arr_start, "[", "]"),
    ) if pos != -1]
    if not candidates:
        return stripped
    start, opener, closer = min(candidates, key=lambda triple: triple[0])

    depth = 0
    in_string = False
    escape = False
    for idx in range(start, len(stripped)):
        ch = stripped[idx]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return stripped[start : idx + 1]

    return stripped


def extract_anthropic_text(response) -> str:
    """Concatenate text blocks from an Anthropic SDK Messages response."""
    parts: list[str] = []
    for block in getattr(response, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts).strip()


def extract_openai_text(response) -> str:
    """Concatenate text from an OpenAI Responses API response."""
    output_text = getattr(response, "output_text", None)
    if output_text:
        return output_text.strip()

    parts: list[str] = []
    for item in getattr(response, "output", []) or []:
        for content in getattr(item, "content", []) or []:
            text = getattr(content, "text", None)
            if text:
                parts.append(text)
    return "\n".join(parts).strip()


__all__ = [
    "LLMUnavailableError",
    "call_claude_code",
    "extract_anthropic_text",
    "extract_openai_text",
    "unwrap_json_response",
]
