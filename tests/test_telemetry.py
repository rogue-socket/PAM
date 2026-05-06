"""Unit tests for pam.telemetry.append_log_line.

Audit O1: telemetry log writes were not atomic and not fsync'd, leaving torn
JSON lines on crash. The new helper flushes + fsyncs before close. Tests
cover happy path, fsync invocation, and the silent-failure contract for
disk-error scenarios so telemetry never blocks the caller.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pam.telemetry import append_log_line


class AppendLogLineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.log_path = Path(self.temp_dir.name) / "log.jsonl"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_appends_one_json_line(self) -> None:
        append_log_line(self.log_path, {"event": "ingest", "id": "abc"})
        append_log_line(self.log_path, {"event": "query", "raw_query": "hello"})

        lines = self.log_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0]), {"event": "ingest", "id": "abc"})
        self.assertEqual(json.loads(lines[1]), {"event": "query", "raw_query": "hello"})

    def test_calls_fsync_after_write(self) -> None:
        with mock.patch("pam.telemetry.os.fsync") as fsync_mock:
            append_log_line(self.log_path, {"event": "test"})
        fsync_mock.assert_called_once()
        # The arg is a file descriptor int.
        self.assertIsInstance(fsync_mock.call_args.args[0], int)

    def test_oserror_during_open_is_swallowed(self) -> None:
        """Telemetry must never propagate OS errors to the caller."""
        bogus_path = Path("/nonexistent/dir/that/should/not/exist/log.jsonl")
        try:
            append_log_line(bogus_path, {"event": "test"})
        except OSError:
            self.fail("append_log_line must swallow OSError, not propagate")

    def test_oserror_during_fsync_is_swallowed(self) -> None:
        with mock.patch("pam.telemetry.os.fsync", side_effect=OSError("disk full")):
            try:
                append_log_line(self.log_path, {"event": "test"})
            except OSError:
                self.fail("append_log_line must swallow fsync OSError")

    def test_payload_with_unicode_is_ascii_escaped(self) -> None:
        """ensure_ascii=True keeps the JSONL parseable by tools that expect ASCII."""
        append_log_line(self.log_path, {"name": "Anya — Norway café"})
        line = self.log_path.read_text(encoding="utf-8").splitlines()[0]
        # Confirm the line contains escaped sequences rather than raw non-ASCII.
        self.assertIn("\\u", line)
        # Round-trips back to the original string via json.loads.
        self.assertEqual(json.loads(line), {"name": "Anya — Norway café"})


if __name__ == "__main__":
    unittest.main()
