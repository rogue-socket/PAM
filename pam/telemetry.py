"""Best-effort telemetry log writes.

Single helper for append-with-flush+fsync used by ingestion, retrieval,
lifecycle, and feedback. Replaces four scattered `with LOG_PATH.open("a")`
sites that previously left torn JSON lines on crash because they neither
flushed user-space buffers nor fsync'd before the file handle closed.

This is best-effort: telemetry remains *not* transactional with SQLite
commits. The audit O1 fix narrows the corruption window from "any process
exit between write() and the OS flushing the buffer" to "a hardware-level
crash between fsync and the next disk barrier." Good enough for kayo's
audit trail without the cost of a per-event transaction.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


def append_log_line(log_path: Path, payload: dict) -> None:
    """Append one JSON line, flushed and fsync'd.

    Caller is responsible for the payload structure; this helper does not
    add timestamps. On any exception the call falls back silently — telemetry
    must never block a successful PAM operation.
    """
    try:
        line = json.dumps(payload, ensure_ascii=True) + "\n"
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError:
        # Disk full, permission error, etc. Telemetry is best-effort; never
        # propagate to the caller's hot path.
        return


__all__ = ["append_log_line"]
