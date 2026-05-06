"""Run all three PAM evaluation suites through the Copilot CLI and produce a combined report."""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
EVAL_SCRIPT = ROOT / "scripts" / "run_copilot_cli_eval.py"

SUITES = ["detailed", "large", "hard"]
MODEL = "claude-opus-4.6"
BATCH_SIZE = 20


def run_suite(suite: str) -> dict:
    cmd = [
        str(PYTHON),
        str(EVAL_SCRIPT),
        "--suite", suite,
        "--model", MODEL,
        "--batch-size", str(BATCH_SIZE),
        "--include-misses",
    ]
    print(f"\n{'='*60}", file=sys.stderr, flush=True)
    print(f"  STARTING SUITE: {suite.upper()}  (model={MODEL})", file=sys.stderr, flush=True)
    print(f"{'='*60}\n", file=sys.stderr, flush=True)

    result = subprocess.run(
        cmd,
        cwd=ROOT,
        capture_output=True,
        check=False,
    )

    stdout = result.stdout.decode("utf-8", errors="replace").strip()
    stderr = result.stderr.decode("utf-8", errors="replace").strip()

    # Stream the stderr logs to our stderr so the user sees progress
    if stderr:
        print(stderr, file=sys.stderr, flush=True)

    if result.returncode != 0:
        return {"suite": suite, "error": stderr or stdout or f"exit code {result.returncode}"}

    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return {"suite": suite, "error": f"invalid JSON: {stdout[:500]}"}


def main() -> int:
    started_at = datetime.now(timezone.utc).isoformat()
    results = []

    for suite in SUITES:
        payload = run_suite(suite)
        results.append(payload)

    finished_at = datetime.now(timezone.utc).isoformat()

    report = {
        "model": MODEL,
        "started_at": started_at,
        "finished_at": finished_at,
        "suites": results,
    }

    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
