from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from pam.agent_interface import format_for_context_window, query_for_agent


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CHAT_MODEL = "claude-sonnet-4.5"


class ChatAgentError(RuntimeError):
    """Raised when the PAM-backed chat agent cannot complete a turn."""


@dataclass
class ChatResponse:
    answer: str
    retrieved_context: str


def _windows_copilot_candidates() -> tuple[str, ...]:
    appdata = Path(os.getenv("APPDATA", ""))
    return (
        shutil.which("copilot.cmd") or "",
        str(appdata / "npm" / "copilot.cmd"),
        str(
            appdata
            / "Code"
            / "User"
            / "globalStorage"
            / "github.copilot-chat"
            / "copilotCli"
            / "copilot.bat"
        ),
    )


def get_copilot_command_prefix() -> tuple[str, ...]:
    """Resolve the GitHub Copilot CLI invocation for the current platform.

    Failures are not cached so a transient PATH miss can be retried after the
    user installs/repairs the CLI without restarting the process.
    """
    on_path = shutil.which("copilot")
    if on_path:
        return (on_path,)

    if sys.platform == "win32":
        appdata = Path(os.getenv("APPDATA", ""))
        npm_loader = appdata / "npm" / "node_modules" / "@github" / "copilot" / "npm-loader.js"
        node_exe = shutil.which("node")
        if node_exe and npm_loader.exists():
            return (node_exe, str(npm_loader))
        for candidate in _windows_copilot_candidates():
            if candidate and Path(candidate).exists():
                return (candidate,)

    raise ChatAgentError(
        "Could not locate the GitHub Copilot CLI executable. "
        "Install it from https://docs.github.com/en/copilot/github-copilot-in-the-cli "
        "and ensure `copilot` is on PATH."
    )


def retrieve_context_for_chat(
    raw_query: str,
    *,
    top_k: int,
    workspace_id: str | Path | None = None,
) -> str:
    result = query_for_agent(raw_query, top_k=top_k, workspace_id=workspace_id)
    return format_for_context_window(result)


def build_chat_prompt(raw_query: str, retrieved_context: str) -> str:
    return (
        "You are a conversational assistant grounded in PAM memory.\n"
        f"User question: {raw_query}\n\n"
        "Rules:\n"
        "- Answer using only the PAM memory context below.\n"
        "- If the memory is insufficient, reply exactly: I don't know from PAM memory.\n"
        "- Keep the answer concise, factual, and directly responsive.\n"
        "- Do not claim to have inspected files or outside sources unless they appear in the PAM memory context.\n\n"
        "PAM memory context:\n"
        f"{retrieved_context}"
    )


def run_copilot_prompt(
    prompt: str,
    *,
    model: str = DEFAULT_CHAT_MODEL,
    timeout: int = 300,
    cwd: str | Path | None = None,
) -> str:
    command = [
        *get_copilot_command_prefix(),
        "-p",
        prompt,
        "--model",
        model,
        "--no-ask-user",
        "--stream",
        "off",
        "-s",
        "--output-format",
        "text",
    ]

    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd) if cwd is not None else None,
            env=os.environ.copy(),
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ChatAgentError(f"copilot query timed out after {timeout}s") from exc

    stdout = completed.stdout.decode("utf-8", errors="replace").strip()
    stderr = completed.stderr.decode("utf-8", errors="replace").strip()
    if completed.returncode != 0:
        raise ChatAgentError(stderr or stdout or f"copilot exited with code {completed.returncode}")
    return stdout


def answer_with_pam(
    raw_query: str,
    *,
    model: str = DEFAULT_CHAT_MODEL,
    top_k: int = 5,
    workspace_id: str | Path | None = None,
    cwd: str | Path | None = None,
) -> ChatResponse:
    """Run a PAM-grounded Copilot turn.

    `cwd` is the working directory for the Copilot subprocess. Defaults to the
    caller's CWD so kayo's Copilot context matches the user's project, not the
    PAM repo. Pass an explicit value to override.
    """
    retrieved_context = retrieve_context_for_chat(raw_query, top_k=top_k, workspace_id=workspace_id)
    answer = run_copilot_prompt(
        build_chat_prompt(raw_query, retrieved_context),
        model=model,
        cwd=cwd if cwd is not None else Path.cwd(),
    )
    return ChatResponse(answer=answer, retrieved_context=retrieved_context)


__all__ = [
    "ChatAgentError",
    "ChatResponse",
    "DEFAULT_CHAT_MODEL",
    "answer_with_pam",
    "build_chat_prompt",
    "get_copilot_command_prefix",
    "retrieve_context_for_chat",
    "run_copilot_prompt",
]