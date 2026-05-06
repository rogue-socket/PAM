"""Unit tests for pam.llm_clients (the shared LLM primitives).

Covers (1) the `claude_code` provider plumbing, (2) the consolidated
`LLMUnavailableError` class identity that is now shared between
pam.ingestion.llm and pam.retrieval.query_parser.
"""

from __future__ import annotations

import subprocess
import unittest
from unittest import mock

import json

import pam.ingestion.llm as ingestion_llm
import pam.llm_clients as llm_clients
import pam.retrieval.query_parser as query_parser
from pam.llm_clients import LLMUnavailableError, call_claude_code, unwrap_json_response


class CallClaudeCodeTests(unittest.TestCase):
    def setUp(self) -> None:
        llm_clients._resolve_claude_cli.cache_clear()

    def tearDown(self) -> None:
        llm_clients._resolve_claude_cli.cache_clear()

    def test_returns_stdout_text_on_success(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["claude"], returncode=0, stdout=b"summary text\n", stderr=b""
        )
        with mock.patch.object(
            llm_clients.shutil, "which", return_value="/usr/local/bin/claude"
        ), mock.patch.object(llm_clients.subprocess, "run", return_value=completed) as run_mock:
            result = call_claude_code("hello", model="claude-opus-4-7", timeout=30)

        self.assertEqual(result, "summary text")
        command = run_mock.call_args.args[0]
        self.assertEqual(command[0], "/usr/local/bin/claude")
        self.assertIn("-p", command)
        self.assertIn("hello", command)
        self.assertIn("--model", command)
        self.assertIn("claude-opus-4-7", command)
        self.assertIn("--output-format", command)
        self.assertIn("text", command)
        # Stdin must be DEVNULL so the CLI does not pick up unrelated context.
        self.assertEqual(run_mock.call_args.kwargs["stdin"], subprocess.DEVNULL)

    def test_omits_model_flag_when_not_supplied(self) -> None:
        completed = subprocess.CompletedProcess(args=["claude"], returncode=0, stdout=b"ok", stderr=b"")
        with mock.patch.object(
            llm_clients.shutil, "which", return_value="/usr/local/bin/claude"
        ), mock.patch.object(llm_clients.subprocess, "run", return_value=completed) as run_mock:
            call_claude_code("hello")

        command = run_mock.call_args.args[0]
        self.assertNotIn("--model", command)

    def test_raises_unavailable_when_cli_missing(self) -> None:
        with mock.patch.object(llm_clients.shutil, "which", return_value=None):
            with self.assertRaises(LLMUnavailableError):
                call_claude_code("hello")

    def test_raises_unavailable_on_nonzero_exit(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["claude"], returncode=2, stdout=b"", stderr=b"claude: not authenticated"
        )
        with mock.patch.object(
            llm_clients.shutil, "which", return_value="/usr/local/bin/claude"
        ), mock.patch.object(llm_clients.subprocess, "run", return_value=completed):
            with self.assertRaisesRegex(LLMUnavailableError, "not authenticated"):
                call_claude_code("hello")

    def test_raises_unavailable_on_timeout(self) -> None:
        with mock.patch.object(
            llm_clients.shutil, "which", return_value="/usr/local/bin/claude"
        ), mock.patch.object(
            llm_clients.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(cmd=["claude"], timeout=1),
        ):
            with self.assertRaisesRegex(LLMUnavailableError, "timed out"):
                call_claude_code("hello", timeout=1)

    def test_raises_unavailable_when_binary_disappears_between_lookup_and_exec(self) -> None:
        with mock.patch.object(
            llm_clients.shutil, "which", return_value="/usr/local/bin/claude"
        ), mock.patch.object(
            llm_clients.subprocess,
            "run",
            side_effect=FileNotFoundError(2, "No such file or directory"),
        ):
            with self.assertRaises(LLMUnavailableError):
                call_claude_code("hello")


class SharedExceptionIdentityTests(unittest.TestCase):
    """Both call sites must surface the same exception class.

    Pre-consolidation, pam.ingestion.llm.LLMUnavailableError and
    pam.retrieval.query_parser.LLMUnavailableError were distinct classes —
    `except LLMUnavailableError` from one location did not catch the other.
    """

    def test_ingestion_and_query_parser_share_one_exception_class(self) -> None:
        self.assertIs(ingestion_llm.LLMUnavailableError, llm_clients.LLMUnavailableError)
        self.assertIs(query_parser.LLMUnavailableError, llm_clients.LLMUnavailableError)


class ClaudeCodeProviderDispatchTests(unittest.TestCase):
    """Both _call_llm and _invoke_llm must route to call_claude_code when
    LLM_PROVIDER='claude_code', without touching the Anthropic / OpenAI SDKs.
    """

    def test_ingestion_dispatches_to_claude_code(self) -> None:
        with mock.patch.object(ingestion_llm, "LLM_PROVIDER", "claude_code"), mock.patch.object(
            ingestion_llm, "call_claude_code", return_value="from claude code"
        ) as call_mock:
            result = ingestion_llm._call_llm("summarize this")

        self.assertEqual(result, "from claude code")
        call_mock.assert_called_once()
        # First positional arg is the prompt.
        self.assertEqual(call_mock.call_args.args[0], "summarize this")

    def test_query_parser_dispatches_to_claude_code(self) -> None:
        from datetime import date

        with mock.patch.object(query_parser, "LLM_PROVIDER", "claude_code"), mock.patch.object(
            query_parser, "call_claude_code", return_value='{"keywords": ["x"]}'
        ) as call_mock:
            result = query_parser._invoke_llm("when did X happen?", today=date(2026, 5, 6))

        self.assertEqual(result, '{"keywords": ["x"]}')
        call_mock.assert_called_once()


class UnwrapJsonResponseTests(unittest.TestCase):
    def test_passes_through_bare_object(self) -> None:
        text = '{"keywords": ["x"]}'
        self.assertEqual(json.loads(unwrap_json_response(text)), {"keywords": ["x"]})

    def test_passes_through_bare_array(self) -> None:
        text = '[{"name": "Alice", "category": "person"}]'
        self.assertEqual(
            json.loads(unwrap_json_response(text)),
            [{"name": "Alice", "category": "person"}],
        )

    def test_strips_markdown_json_fence(self) -> None:
        text = '```json\n{"keywords": ["x"]}\n```'
        self.assertEqual(json.loads(unwrap_json_response(text)), {"keywords": ["x"]})

    def test_strips_plain_markdown_fence(self) -> None:
        text = '```\n{"keywords": ["x"]}\n```'
        self.assertEqual(json.loads(unwrap_json_response(text)), {"keywords": ["x"]})

    def test_extracts_json_after_prose_preamble(self) -> None:
        text = 'Sure, here is the JSON you asked for:\n\n{"keywords": ["x", "y"], "intent": "lookup"}'
        self.assertEqual(
            json.loads(unwrap_json_response(text)),
            {"keywords": ["x", "y"], "intent": "lookup"},
        )

    def test_handles_nested_braces_and_quoted_braces(self) -> None:
        text = 'Result: {"a": {"b": "}{"}, "c": [1, 2]}'
        unwrapped = unwrap_json_response(text)
        self.assertEqual(json.loads(unwrapped), {"a": {"b": "}{"}, "c": [1, 2]})

    def test_extracts_array_after_prose(self) -> None:
        text = 'Here are the entities:\n[{"name": "X", "category": "person"}]'
        self.assertEqual(
            json.loads(unwrap_json_response(text)),
            [{"name": "X", "category": "person"}],
        )

    def test_returns_stripped_input_when_no_json_present(self) -> None:
        self.assertEqual(unwrap_json_response("  no json here  "), "no json here")

    def test_handles_empty_string(self) -> None:
        self.assertEqual(unwrap_json_response(""), "")


if __name__ == "__main__":
    unittest.main()
