"""Transaction helper for multi-step write orchestration.

Low-level mutators (create_node, create_edge, ...) accept a `commit`
keyword and skip their auto-commit when called inside a `transaction()`
block. The helper commits once on successful exit and rolls back on
exception. Nestable via SAVEPOINT — `link_entities_detailed` can wrap
its own writes even when called from inside `ingest()`'s transaction.
"""
from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from typing import Iterator


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[None]:
    """Atomic transaction over `conn`. Nested calls use SAVEPOINTs."""
    if conn.in_transaction:
        name = f"sp_{uuid.uuid4().hex[:12]}"
        conn.execute(f"SAVEPOINT {name}")
        try:
            yield
        except BaseException:
            conn.execute(f"ROLLBACK TO SAVEPOINT {name}")
            conn.execute(f"RELEASE SAVEPOINT {name}")
            raise
        else:
            conn.execute(f"RELEASE SAVEPOINT {name}")
    else:
        conn.execute("BEGIN")
        try:
            yield
        except BaseException:
            conn.rollback()
            raise
        else:
            conn.commit()
