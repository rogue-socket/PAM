from __future__ import annotations

import argparse
import importlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest import mock

import pam.db.schema as schema_module
from pam.agent_interface import ingest_for_agent
from pam.db.schema import get_connection, initialize
from pam.retrieval.query_parser import parse_query_with_metadata


eval_module = importlib.import_module("scripts.run_copilot_cli_eval")


class CopilotCliEvalHarnessTests(unittest.TestCase):
    def setUp(self) -> None:
        eval_module._get_copilot_command_prefix.cache_clear()
        eval_module._get_claude_command_prefix.cache_clear()

    def tearDown(self) -> None:
        eval_module._get_copilot_command_prefix.cache_clear()
        eval_module._get_claude_command_prefix.cache_clear()

    def test_find_copilot_command_prefix_prefers_path_when_available(self) -> None:
        with mock.patch.object(eval_module.shutil, "which", return_value="/usr/local/bin/copilot"):
            command_prefix = eval_module._find_copilot_command_prefix()
        self.assertEqual(command_prefix, ("/usr/local/bin/copilot",))

    def test_find_copilot_command_prefix_prefers_node_loader_on_windows(self) -> None:
        appdata = r"C:\Users\tester\AppData\Roaming"
        expected_loader = str(Path(appdata) / "npm" / "node_modules" / "@github" / "copilot" / "npm-loader.js")

        def fake_which(command: str) -> str | None:
            if command == "node":
                return r"C:\Program Files\nodejs\node.exe"
            return None

        def fake_exists(path_self: Path) -> bool:
            return str(path_self) == expected_loader

        with mock.patch.object(eval_module.sys, "platform", "win32"), mock.patch.dict(
            os.environ, {"APPDATA": appdata}, clear=False
        ), mock.patch.object(
            eval_module.shutil,
            "which",
            side_effect=fake_which,
        ), mock.patch.object(eval_module.Path, "exists", autospec=True, side_effect=fake_exists):
            command_prefix = eval_module._find_copilot_command_prefix()

        self.assertEqual(command_prefix, (r"C:\Program Files\nodejs\node.exe", expected_loader))

    def test_find_copilot_command_prefix_raises_when_no_candidate_exists(self) -> None:
        with mock.patch.object(eval_module.sys, "platform", "win32"), mock.patch.dict(
            os.environ, {"APPDATA": r"C:\Users\tester\AppData\Roaming"}, clear=False
        ), mock.patch.object(
            eval_module.shutil,
            "which",
            return_value=None,
        ), mock.patch.object(eval_module.Path, "exists", autospec=True, return_value=False):
            with self.assertRaises(FileNotFoundError):
                eval_module._find_copilot_command_prefix()

    def test_find_copilot_command_prefix_skips_windows_paths_off_windows(self) -> None:
        """On non-Windows, missing PATH-resolved copilot should fail fast — no APPDATA fallback."""
        with mock.patch.object(eval_module.sys, "platform", "darwin"), mock.patch.object(
            eval_module.shutil,
            "which",
            return_value=None,
        ):
            with self.assertRaises(FileNotFoundError):
                eval_module._find_copilot_command_prefix()

    def test_find_claude_command_prefix_uses_path(self) -> None:
        with mock.patch.object(eval_module.shutil, "which", return_value="/usr/local/bin/claude"):
            command_prefix = eval_module._find_claude_command_prefix()
        self.assertEqual(command_prefix, ("/usr/local/bin/claude",))

    def test_find_claude_command_prefix_raises_when_missing(self) -> None:
        with mock.patch.object(eval_module.shutil, "which", return_value=None):
            with self.assertRaises(FileNotFoundError):
                eval_module._find_claude_command_prefix()

    def test_run_copilot_query_builds_command_and_returns_stdout(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["copilot.cmd"],
            returncode=0,
            stdout=b"Launch moved to 2026-05-01\n",
            stderr=b"",
        )

        with mock.patch.object(eval_module, "_retrieve_context", return_value="Retrieved PAM results:\n- launch note") as retrieve_mock, mock.patch.object(
            eval_module,
            "_get_copilot_command_prefix",
            return_value=("copilot.cmd",),
        ), mock.patch.object(eval_module.subprocess, "run", return_value=completed) as run_mock:
            answer = eval_module._run_copilot_query(
                "When is the launch now?",
                model="claude-sonnet-4.5",
                top_k=5,
                db_path=Path("pam-test.db"),
                log_path=Path("pam-test.jsonl"),
            )

        self.assertEqual(answer, "Launch moved to 2026-05-01")
        retrieve_mock.assert_called_once_with("When is the launch now?", top_k=5)
        run_kwargs = run_mock.call_args.kwargs
        run_command = run_mock.call_args.args[0]
        self.assertEqual(run_command[0], "copilot.cmd")
        self.assertIn("--model", run_command)
        self.assertIn("claude-sonnet-4.5", run_command)
        self.assertIn("When is the launch now?", run_command[2])
        self.assertIn("Retrieved PAM results:\n- launch note", run_command[2])
        self.assertEqual(run_kwargs["cwd"], eval_module.ROOT)
        self.assertTrue(run_kwargs["capture_output"])
        self.assertEqual(run_kwargs["timeout"], 300)
        self.assertFalse(run_kwargs["check"])

    def test_run_copilot_query_raises_on_timeout(self) -> None:
        with mock.patch.object(eval_module, "_retrieve_context", return_value="Retrieved PAM results"), mock.patch.object(
            eval_module,
            "_get_copilot_command_prefix",
            return_value=("copilot.cmd",),
        ), mock.patch.object(
            eval_module.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(cmd=["copilot.cmd"], timeout=300),
        ):
            with self.assertRaisesRegex(RuntimeError, "timed out"):
                eval_module._run_copilot_query(
                    "When is the launch now?",
                    model="claude-sonnet-4.5",
                    top_k=5,
                    db_path=Path("pam-test.db"),
                    log_path=Path("pam-test.jsonl"),
                )

    def test_run_claude_query_builds_command_and_returns_stdout(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["claude"],
            returncode=0,
            stdout=b"Launch moved to 2026-05-01\n",
            stderr=b"",
        )

        with mock.patch.object(
            eval_module, "_retrieve_context", return_value="Retrieved PAM results:\n- launch note"
        ) as retrieve_mock, mock.patch.object(
            eval_module, "_get_claude_command_prefix", return_value=("/usr/local/bin/claude",)
        ), mock.patch.object(eval_module.subprocess, "run", return_value=completed) as run_mock:
            answer = eval_module._run_claude_query(
                "When is the launch now?",
                model="claude-sonnet-4-5",
                top_k=5,
                db_path=Path("pam-test.db"),
                log_path=Path("pam-test.jsonl"),
            )

        self.assertEqual(answer, "Launch moved to 2026-05-01")
        retrieve_mock.assert_called_once_with("When is the launch now?", top_k=5)
        run_command = run_mock.call_args.args[0]
        self.assertEqual(run_command[0], "/usr/local/bin/claude")
        self.assertIn("-p", run_command)
        self.assertIn("--model", run_command)
        self.assertIn("claude-sonnet-4-5", run_command)
        self.assertIn("--output-format", run_command)
        self.assertIn("text", run_command)
        # Claude CLI must NOT receive Copilot-only flags
        self.assertNotIn("--no-ask-user", run_command)
        self.assertNotIn("--stream", run_command)

    def test_run_claude_query_raises_on_timeout(self) -> None:
        with mock.patch.object(
            eval_module, "_retrieve_context", return_value="Retrieved PAM results"
        ), mock.patch.object(
            eval_module, "_get_claude_command_prefix", return_value=("claude",)
        ), mock.patch.object(
            eval_module.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(cmd=["claude"], timeout=300),
        ):
            with self.assertRaisesRegex(RuntimeError, "timed out"):
                eval_module._run_claude_query(
                    "Q?",
                    model="claude-sonnet-4-5",
                    top_k=5,
                    db_path=Path("pam-test.db"),
                    log_path=Path("pam-test.jsonl"),
                )

    def test_run_backend_query_dispatches(self) -> None:
        with mock.patch.object(eval_module, "_run_copilot_query", return_value="copilot answer") as copilot_mock, mock.patch.object(
            eval_module, "_run_claude_query", return_value="claude answer"
        ) as claude_mock:
            self.assertEqual(
                eval_module._run_backend_query(
                    "copilot",
                    "Q?",
                    model="m",
                    top_k=1,
                    db_path=Path("p"),
                    log_path=Path("l"),
                ),
                "copilot answer",
            )
            self.assertEqual(
                eval_module._run_backend_query(
                    "claude",
                    "Q?",
                    model="m",
                    top_k=1,
                    db_path=Path("p"),
                    log_path=Path("l"),
                ),
                "claude answer",
            )
        copilot_mock.assert_called_once()
        claude_mock.assert_called_once()

    def test_run_backend_query_rejects_unknown_backend(self) -> None:
        with self.assertRaises(ValueError):
            eval_module._run_backend_query(
                "openai",
                "Q?",
                model="m",
                top_k=1,
                db_path=Path("p"),
                log_path=Path("l"),
            )

    def test_parse_args_default_model_depends_on_backend(self) -> None:
        with mock.patch.object(eval_module.sys, "argv", ["prog", "--suite", "detailed", "--backend", "claude"]):
            args = eval_module._parse_args()
        self.assertEqual(args.backend, "claude")
        self.assertEqual(args.model, eval_module.DEFAULT_MODEL_BY_BACKEND["claude"])

        with mock.patch.object(eval_module.sys, "argv", ["prog", "--suite", "detailed", "--backend", "copilot"]):
            args = eval_module._parse_args()
        self.assertEqual(args.backend, "copilot")
        self.assertEqual(args.model, eval_module.DEFAULT_MODEL_BY_BACKEND["copilot"])

    def test_parse_args_explicit_model_overrides_default(self) -> None:
        with mock.patch.object(
            eval_module.sys,
            "argv",
            ["prog", "--suite", "detailed", "--backend", "claude", "--model", "claude-opus-4-7"],
        ):
            args = eval_module._parse_args()
        self.assertEqual(args.model, "claude-opus-4-7")

    def test_eval_paths_recreates_only_requested_suite_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            stale_file = temp_root / "large" / "stale.txt"
            stale_file.parent.mkdir(parents=True, exist_ok=True)
            stale_file.write_text("old output", encoding="utf-8")

            untouched_file = temp_root / "hard" / "keep.txt"
            untouched_file.parent.mkdir(parents=True, exist_ok=True)
            untouched_file.write_text("keep", encoding="utf-8")

            with mock.patch.object(eval_module, "TEMP_ROOT", temp_root):
                eval_root, db_path, log_path = eval_module._eval_paths("large")

            self.assertEqual(eval_root, temp_root / "large")
            self.assertEqual(db_path, temp_root / "large" / "pam.db")
            self.assertEqual(log_path, temp_root / "large" / "pam_log.jsonl")
            self.assertFalse(stale_file.exists())
            self.assertTrue((temp_root / "large" / "link_sources").is_dir())
            self.assertTrue(untouched_file.exists())

    def test_main_sets_env_and_truncates_misses_by_default(self) -> None:
        args = argparse.Namespace(
            suite="large",
            backend="copilot",
            model="claude-sonnet-4.5",
            top_k=7,
            max_queries=5,
            batch_size=2,
            include_misses=False,
        )
        eval_root = Path("tmp-eval")
        db_path = eval_root / "pam.db"
        log_path = eval_root / "pam_log.jsonl"
        fixture = {"corpus": [{"id": "note-1"}], "queries": []}
        summary = {
            "overall_hits": 3,
            "overall_total": 12,
            "overall_score": 25.0,
            "query_type_hits": {"lookup": 3},
            "query_type_totals": {"lookup": 12},
            "misses": [{"index": index, "query": f"query-{index}"} for index in range(12)],
        }

        with mock.patch.dict(os.environ, {}, clear=False), mock.patch.object(eval_module, "_parse_args", return_value=args), mock.patch.object(
            eval_module,
            "_eval_paths",
            return_value=(eval_root, db_path, log_path),
        ), mock.patch.object(eval_module, "_load_fixture", return_value=(fixture, "LargeAgentEvaluationSuiteTests")), mock.patch.object(
            eval_module,
            "_ingest_fixture",
        ) as ingest_mock, mock.patch.object(eval_module, "_evaluate_queries", return_value=summary), mock.patch.object(
            eval_module,
            "_log",
        ), mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
            exit_code = eval_module.main()
            db_path_env = os.environ["PAM_DB_PATH"]
            log_path_env = os.environ["PAM_LOG_PATH"]

        self.assertEqual(exit_code, 0)
        self.assertEqual(db_path_env, str(db_path))
        self.assertEqual(log_path_env, str(log_path))
        ingest_mock.assert_called_once_with(fixture, db_path=db_path, log_path=log_path, link_dir=eval_root / "link_sources")

        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["suite"], "LargeAgentEvaluationSuiteTests")
        self.assertEqual(payload["backend"], "copilot")
        self.assertEqual(payload["model"], "claude-sonnet-4.5")
        self.assertEqual(len(payload["summary"]["misses"]), 10)
        self.assertEqual(payload["summary"]["misses"][0]["index"], 0)
        self.assertEqual(payload["summary"]["misses"][-1]["index"], 9)


class RealCopilotCliEvalIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if os.getenv("PAM_RUN_REAL_COPILOT_TESTS") != "1":
            raise unittest.SkipTest("Set PAM_RUN_REAL_COPILOT_TESTS=1 to run live Copilot CLI integration tests")

        eval_module._get_copilot_command_prefix.cache_clear()
        try:
            eval_module._get_copilot_command_prefix()
        except FileNotFoundError as exc:
            raise unittest.SkipTest(str(exc)) from exc

        _, fallback_used = parse_query_with_metadata(
            "When is the Zephyr Harbor rollout now scheduled?",
            today=date(2026, 4, 24),
        )
        if fallback_used:
            raise unittest.SkipTest("Real query-parser LLM is unavailable; configure the provider before running live Copilot tests")

        cls.model = os.getenv("PAM_REAL_COPILOT_MODEL", "claude-opus-4.6")

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        temp_root = Path(self.temp_dir.name)
        self.db_path = temp_root / "pam-live-copilot.db"
        self.log_path = temp_root / "pam-live-copilot.jsonl"

        self.db_patch = mock.patch.object(schema_module, "DB_PATH", self.db_path)
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)

        self.ingest_log_patch = mock.patch("pam.ingestion.pipeline.LOG_PATH", self.log_path)
        self.ingest_log_patch.start()
        self.addCleanup(self.ingest_log_patch.stop)

        self.query_log_patch = mock.patch("pam.retrieval.search.LOG_PATH", self.log_path)
        self.query_log_patch.start()
        self.addCleanup(self.query_log_patch.stop)

        self.summarize_patch = mock.patch("pam.ingestion.pipeline.summarize", return_value="")
        self.summarize_patch.start()
        self.addCleanup(self.summarize_patch.stop)

        self.entities_patch = mock.patch("pam.ingestion.pipeline.extract_entities", return_value=[])
        self.entities_patch.start()
        self.addCleanup(self.entities_patch.stop)

        self.edge_fact_patch = mock.patch("pam.ingestion.pipeline.generate_edge_fact", return_value="")
        self.edge_fact_patch.start()
        self.addCleanup(self.edge_fact_patch.stop)

        conn = get_connection(self.db_path)
        try:
            initialize(conn)
        finally:
            conn.close()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_live_copilot_query_answers_positive_and_negative_prompts(self) -> None:
        ingest_for_agent(
            "Zephyr Harbor rollout moved to 2026-09-14 after dock testing slipped.",
            kind="note",
            session_id="live-copilot",
            valid_at=datetime(2026, 4, 24, tzinfo=timezone.utc),
            workspace_id=eval_module.ROOT,
        )

        parsed, fallback_used = parse_query_with_metadata(
            "When is the Zephyr Harbor rollout now scheduled?",
            today=date(2026, 4, 24),
        )

        self.assertFalse(fallback_used)
        self.assertIn("zephyr", parsed.keywords)

        positive_answer = eval_module._run_copilot_query(
            "When is the Zephyr Harbor rollout now scheduled?",
            model=self.model,
            top_k=5,
            db_path=self.db_path,
            log_path=self.log_path,
        )
        self.assertTrue(
            eval_module._answer_passes(positive_answer, {"expected_substrings": ["2026-09-14"]}),
            positive_answer,
        )

        negative_answer = eval_module._run_copilot_query(
            "What do we know about velvet orchard ladders?",
            model=self.model,
            top_k=5,
            db_path=self.db_path,
            log_path=self.log_path,
        )
        self.assertTrue(
            eval_module._answer_passes(negative_answer, {"expect_empty": True}),
            negative_answer,
        )


if __name__ == "__main__":
    unittest.main()