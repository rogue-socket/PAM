"""Unit tests for the PAM-grounded chat agent.

These cover the May 2026 fixes to pam.chat_agent:
- Copilot CLI lookup is platform-aware (PATH first; Windows fallbacks gated).
- Failures are no longer cached, so a transient PATH miss is retried.
- `answer_with_pam` defaults the Copilot subprocess cwd to `Path.cwd()` and
  threads an explicit cwd through.
"""

from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path
from unittest import mock

import pam.chat_agent as chat_agent_module
from pam.chat_agent import (
    ChatAgentError,
    ChatResponse,
    answer_with_pam,
    get_copilot_command_prefix,
    run_copilot_prompt,
)


class CopilotLookupTests(unittest.TestCase):
    def test_prefers_path_when_copilot_on_path(self) -> None:
        with mock.patch.object(chat_agent_module.shutil, "which", return_value="/usr/local/bin/copilot"):
            self.assertEqual(get_copilot_command_prefix(), ("/usr/local/bin/copilot",))

    def test_falls_back_to_node_loader_on_windows(self) -> None:
        appdata = r"C:\Users\tester\AppData\Roaming"
        expected_loader = str(Path(appdata) / "npm" / "node_modules" / "@github" / "copilot" / "npm-loader.js")

        def fake_which(command: str) -> str | None:
            if command == "copilot":
                return None
            if command == "node":
                return r"C:\Program Files\nodejs\node.exe"
            return None

        def fake_exists(path_self: Path) -> bool:
            return str(path_self) == expected_loader

        with mock.patch.object(chat_agent_module.sys, "platform", "win32"), mock.patch.dict(
            os.environ, {"APPDATA": appdata}, clear=False
        ), mock.patch.object(
            chat_agent_module.shutil, "which", side_effect=fake_which
        ), mock.patch.object(
            chat_agent_module.Path, "exists", autospec=True, side_effect=fake_exists
        ):
            self.assertEqual(
                get_copilot_command_prefix(),
                (r"C:\Program Files\nodejs\node.exe", expected_loader),
            )

    def test_skips_windows_paths_off_windows(self) -> None:
        """On non-Windows, missing PATH-resolved copilot should fail fast."""
        with mock.patch.object(chat_agent_module.sys, "platform", "darwin"), mock.patch.object(
            chat_agent_module.shutil, "which", return_value=None
        ):
            with self.assertRaises(ChatAgentError):
                get_copilot_command_prefix()

    def test_failures_are_not_cached(self) -> None:
        """Regression: previously @lru_cache'd ChatAgentError persisted forever."""
        which_calls: list[str | None] = [None, "/usr/local/bin/copilot"]

        def fake_which(command: str) -> str | None:
            return which_calls.pop(0)

        with mock.patch.object(chat_agent_module.sys, "platform", "darwin"), mock.patch.object(
            chat_agent_module.shutil, "which", side_effect=fake_which
        ):
            with self.assertRaises(ChatAgentError):
                get_copilot_command_prefix()
            # The next call must hit shutil.which again, not return a cached error.
            self.assertEqual(get_copilot_command_prefix(), ("/usr/local/bin/copilot",))


class RunCopilotPromptTests(unittest.TestCase):
    def test_run_copilot_prompt_passes_cwd_through(self) -> None:
        completed = subprocess.CompletedProcess(args=["copilot"], returncode=0, stdout=b"ok", stderr=b"")
        with mock.patch.object(
            chat_agent_module, "get_copilot_command_prefix", return_value=("copilot",)
        ), mock.patch.object(chat_agent_module.subprocess, "run", return_value=completed) as run_mock:
            run_copilot_prompt("hello", cwd="/tmp/work")

        self.assertEqual(run_mock.call_args.kwargs["cwd"], "/tmp/work")

    def test_run_copilot_prompt_defaults_cwd_to_none_when_not_supplied(self) -> None:
        """No explicit cwd → subprocess inherits the caller's CWD."""
        completed = subprocess.CompletedProcess(args=["copilot"], returncode=0, stdout=b"ok", stderr=b"")
        with mock.patch.object(
            chat_agent_module, "get_copilot_command_prefix", return_value=("copilot",)
        ), mock.patch.object(chat_agent_module.subprocess, "run", return_value=completed) as run_mock:
            run_copilot_prompt("hello")

        self.assertIsNone(run_mock.call_args.kwargs["cwd"])

    def test_run_copilot_prompt_raises_chat_agent_error_on_nonzero(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["copilot"], returncode=2, stdout=b"", stderr=b"copilot: not authenticated"
        )
        with mock.patch.object(
            chat_agent_module, "get_copilot_command_prefix", return_value=("copilot",)
        ), mock.patch.object(chat_agent_module.subprocess, "run", return_value=completed):
            with self.assertRaisesRegex(ChatAgentError, "not authenticated"):
                run_copilot_prompt("hello")

    def test_run_copilot_prompt_raises_on_timeout(self) -> None:
        with mock.patch.object(
            chat_agent_module, "get_copilot_command_prefix", return_value=("copilot",)
        ), mock.patch.object(
            chat_agent_module.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(cmd=["copilot"], timeout=300),
        ):
            with self.assertRaisesRegex(ChatAgentError, "timed out"):
                run_copilot_prompt("hello", timeout=300)


class AnswerWithPamTests(unittest.TestCase):
    """Behavioral: defaulting cwd to Path.cwd() and threading explicit cwd."""

    def test_defaults_subprocess_cwd_to_caller_cwd(self) -> None:
        retrieved = "---\n## Retrieved Memories (0 results)\n---"
        with mock.patch.object(
            chat_agent_module, "retrieve_context_for_chat", return_value=retrieved
        ), mock.patch.object(chat_agent_module, "run_copilot_prompt", return_value="answer") as prompt_mock:
            response = answer_with_pam("Q?", model="claude-sonnet-4.5", top_k=3)

        self.assertIsInstance(response, ChatResponse)
        # cwd should equal Path.cwd() when caller does not pass one.
        self.assertEqual(prompt_mock.call_args.kwargs["cwd"], Path.cwd())

    def test_explicit_cwd_is_threaded_to_subprocess(self) -> None:
        retrieved = "---\n## Retrieved Memories (0 results)\n---"
        custom_cwd = Path("/Users/agent/project-x")
        with mock.patch.object(
            chat_agent_module, "retrieve_context_for_chat", return_value=retrieved
        ), mock.patch.object(chat_agent_module, "run_copilot_prompt", return_value="answer") as prompt_mock:
            answer_with_pam("Q?", model="claude-sonnet-4.5", top_k=3, cwd=custom_cwd)

        self.assertEqual(prompt_mock.call_args.kwargs["cwd"], custom_cwd)

    def test_workspace_id_is_passed_to_retrieval_not_subprocess(self) -> None:
        """workspace_id selects PAM memories; cwd controls the Copilot subprocess context."""
        retrieved = "---\n## Retrieved Memories (0 results)\n---"
        with mock.patch.object(
            chat_agent_module, "retrieve_context_for_chat", return_value=retrieved
        ) as retrieve_mock, mock.patch.object(
            chat_agent_module, "run_copilot_prompt", return_value="answer"
        ) as prompt_mock:
            answer_with_pam(
                "Q?",
                model="claude-sonnet-4.5",
                top_k=3,
                workspace_id=Path("/workspace/A"),
                cwd=Path("/cwd/B"),
            )

        self.assertEqual(retrieve_mock.call_args.kwargs["workspace_id"], Path("/workspace/A"))
        self.assertEqual(prompt_mock.call_args.kwargs["cwd"], Path("/cwd/B"))


if __name__ == "__main__":
    unittest.main()
