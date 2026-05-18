from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from config import DB_PATH


logger = logging.getLogger(__name__)


CONNECTION_PRAGMAS = (
    "PRAGMA journal_mode = WAL",
    "PRAGMA foreign_keys = ON",
    "PRAGMA busy_timeout = 5000",
)


# Per-process set of DB paths whose health has already been checked. Keyed by
# resolved path so different relative forms hit the same entry. Cleared by
# tests via _HEALTH_CHECKED_PATHS.clear().
_HEALTH_CHECKED_PATHS: set[str] = set()

# Tracks whether sqlite-vec failed to load on a given connection so we only
# warn once per process.
_VEC_EXT_WARNED = False


def _try_load_vec_extension(conn: sqlite3.Connection) -> bool:
    """Best-effort load of sqlite-vec. Returns True if loaded.

    Failure is non-fatal — embedding-aware retrieval tier-downs to FTS-only
    per the deterministic-fallback contract.
    """
    global _VEC_EXT_WARNED
    try:
        import sqlite_vec
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        return True
    except Exception as exc:
        if not _VEC_EXT_WARNED:
            logger.warning("sqlite-vec extension unavailable (%s); vector retrieval disabled", exc)
            _VEC_EXT_WARNED = True
        return False


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def datetime_to_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def utcnow_iso() -> str:
    return datetime_to_iso(utcnow())


def iso_to_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _current_workspace_id() -> str:
    return str(Path.cwd().resolve())


def _apply_connection_pragmas(conn: sqlite3.Connection) -> None:
    for pragma in CONNECTION_PRAGMAS:
        conn.execute(pragma)


def _count_query(conn: sqlite3.Connection, query: str) -> int:
    return conn.execute(query).fetchone()[0]


def get_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Return a new connection with required pragmas set."""
    target = db_path or DB_PATH
    conn = sqlite3.connect(str(target))
    _apply_connection_pragmas(conn)
    conn.row_factory = sqlite3.Row
    _try_load_vec_extension(conn)
    return conn


def get_initialized_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    conn = get_connection(db_path)
    initialize(conn)
    _check_health_once(conn, db_path)
    return conn


def _check_health_once(conn: sqlite3.Connection, db_path: Path | str | None) -> None:
    """Run check_database_health once per process per DB path. Warns on drift."""
    target = db_path or DB_PATH
    key = str(Path(str(target)).resolve())
    if key in _HEALTH_CHECKED_PATHS:
        return
    _HEALTH_CHECKED_PATHS.add(key)
    try:
        report = check_database_health(conn)
    except sqlite3.Error as exc:
        logger.warning("check_database_health failed for %s: %s", key, exc)
        return
    if not report["is_healthy"]:
        logger.warning(
            "FTS drift detected for %s: missing_fts_rows=%s orphaned_fts_rows=%s nodes_count=%s",
            key,
            report["missing_fts_rows"],
            report["orphaned_fts_rows"],
            report["nodes_count"],
        )


def resolve_workspace_id(workspace_id: Path | str | None = None) -> str:
    if workspace_id is None:
        return _current_workspace_id()

    text = str(workspace_id).strip()
    if not text:
        return _current_workspace_id()
    return str(Path(text).resolve())


def migrate_v1(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS nodes (
            id           TEXT PRIMARY KEY,
            type         TEXT NOT NULL CHECK(type IN ('event','entity','note','source')),
            title        TEXT NOT NULL,
            content      TEXT NOT NULL DEFAULT '',
            summary      TEXT NOT NULL DEFAULT '',
            content_hash TEXT NOT NULL DEFAULT '',
            created_at   TEXT NOT NULL,
            valid_at     TEXT NOT NULL,
            updated_at   TEXT NOT NULL,
            tags         TEXT NOT NULL DEFAULT '[]',
            session_id   TEXT,
            importance   REAL NOT NULL DEFAULT 0.5
                             CHECK(importance >= 0.0 AND importance <= 1.0),
            access_count INTEGER NOT NULL DEFAULT 0,
            status       TEXT NOT NULL DEFAULT 'active'
                             CHECK(status IN ('active','draft','reference','archived')),
            metadata     TEXT NOT NULL DEFAULT '{}',
            workspace_id TEXT NOT NULL DEFAULT ''
        );

        CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type);
        CREATE INDEX IF NOT EXISTS idx_nodes_status ON nodes(status);
        CREATE INDEX IF NOT EXISTS idx_nodes_created_at ON nodes(created_at);
        CREATE INDEX IF NOT EXISTS idx_nodes_valid_at ON nodes(valid_at);
        CREATE INDEX IF NOT EXISTS idx_nodes_session_id ON nodes(session_id);
        CREATE INDEX IF NOT EXISTS idx_nodes_workspace_id ON nodes(workspace_id);
        CREATE INDEX IF NOT EXISTS idx_nodes_content_hash ON nodes(content_hash)
            WHERE content_hash != '';

        CREATE TABLE IF NOT EXISTS edges (
            source_id  TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
            target_id  TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
            relation   TEXT NOT NULL CHECK(relation IN
                           ('REFERS_TO','DERIVED_FROM','RELATED','CONTRADICTS','SUPERSEDES')),
            weight     REAL NOT NULL DEFAULT 1.0,
            fact       TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            PRIMARY KEY (source_id, target_id, relation)
        );

        CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
        CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);

        CREATE VIRTUAL TABLE IF NOT EXISTS fts_index USING fts5(
            node_id UNINDEXED,
            title,
            content,
            summary,
            tokenize='porter unicode61'
        );

        CREATE TRIGGER IF NOT EXISTS nodes_ai AFTER INSERT ON nodes BEGIN
            INSERT INTO fts_index(node_id, title, content, summary)
            VALUES (new.id, new.title, new.content, new.summary);
        END;

        CREATE TRIGGER IF NOT EXISTS nodes_au AFTER UPDATE ON nodes BEGIN
            DELETE FROM fts_index WHERE node_id = old.id;
            INSERT INTO fts_index(node_id, title, content, summary)
            VALUES (new.id, new.title, new.content, new.summary);
        END;

        CREATE TRIGGER IF NOT EXISTS nodes_ad AFTER DELETE ON nodes BEGIN
            DELETE FROM fts_index WHERE node_id = old.id;
        END;
        """
    )


def migrate_v2(conn: sqlite3.Connection) -> None:
    """Add vec_nodes virtual table for hybrid retrieval.

    No-op if sqlite-vec isn't loaded — the schema_version row still gets
    written so we don't retry on every open. The system runs FTS-only
    until the extension becomes available; backfill is a separate migration.
    """
    from pam.embeddings import EMBEDDING_DIM

    has_vec = bool(conn.execute("SELECT 1 FROM pragma_function_list WHERE name = 'vec_version'").fetchone())
    if not has_vec:
        return

    conn.executescript(
        f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS vec_nodes USING vec0(
            embedding FLOAT[{EMBEDDING_DIM}]
        );

        CREATE TABLE IF NOT EXISTS vec_node_map (
            node_id TEXT PRIMARY KEY REFERENCES nodes(id) ON DELETE CASCADE,
            rowid INTEGER NOT NULL UNIQUE
        );

        CREATE INDEX IF NOT EXISTS idx_vec_node_map_rowid ON vec_node_map(rowid);

        CREATE TRIGGER IF NOT EXISTS vec_nodes_after_node_delete
        AFTER DELETE ON nodes BEGIN
            DELETE FROM vec_nodes WHERE rowid IN (SELECT rowid FROM vec_node_map WHERE node_id = old.id);
        END;
        """
    )


MIGRATIONS = {
    1: ("Initial schema — nodes, edges, fts_index, triggers", migrate_v1),
    2: ("Hybrid retrieval — vec_nodes virtual table + node_id map", migrate_v2),
}


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}


def _ensure_schema_compatibility(conn: sqlite3.Connection) -> None:
    node_columns = _table_columns(conn, "nodes")
    if "workspace_id" not in node_columns:
        conn.execute("ALTER TABLE nodes ADD COLUMN workspace_id TEXT NOT NULL DEFAULT ''")

    conn.execute("CREATE INDEX IF NOT EXISTS idx_nodes_workspace_id ON nodes(workspace_id)")
    needs_backfill = conn.execute(
        "SELECT 1 FROM nodes WHERE workspace_id IS NULL OR workspace_id = '' LIMIT 1"
    ).fetchone()
    if needs_backfill:
        conn.execute(
            "UPDATE nodes SET workspace_id = ? WHERE workspace_id IS NULL OR workspace_id = ''",
            (resolve_workspace_id(),),
        )
        conn.commit()


def initialize(conn: sqlite3.Connection) -> None:
    """Create schema_version table and apply pending migrations."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER NOT NULL,
            applied_at TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.commit()
    apply_migrations(conn)
    _ensure_schema_compatibility(conn)


def check_database_health(conn: sqlite3.Connection) -> dict[str, int | bool]:
    nodes_count = _count_query(conn, "SELECT COUNT(*) FROM nodes")
    missing_fts_rows = _count_query(
        conn,
        """
        SELECT COUNT(*)
        FROM nodes n
        LEFT JOIN fts_index f ON f.node_id = n.id
        WHERE f.node_id IS NULL
        """
    )
    orphaned_fts_rows = _count_query(
        conn,
        """
        SELECT COUNT(*)
        FROM fts_index f
        LEFT JOIN nodes n ON n.id = f.node_id
        WHERE n.id IS NULL
        """
    )
    return {
        "is_healthy": missing_fts_rows == 0 and orphaned_fts_rows == 0,
        "nodes_count": nodes_count,
        "missing_fts_rows": missing_fts_rows,
        "orphaned_fts_rows": orphaned_fts_rows,
    }


def doctor_report(conn: sqlite3.Connection) -> dict[str, object]:
    """Operator-facing health snapshot. Wraps check_database_health with
    schema version, SQLite integrity, and vector-channel coverage.
    """
    from pam.embeddings import is_available as embeddings_available

    base = check_database_health(conn)
    schema_version = get_current_version(conn)

    integrity_row = conn.execute("PRAGMA integrity_check").fetchone()
    integrity_result = integrity_row[0] if integrity_row else "unknown"
    integrity_ok = integrity_result == "ok"

    vec_table_present = bool(
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='vec_node_map'"
        ).fetchone()
    )
    nodes_missing_embeddings = 0
    if vec_table_present:
        nodes_missing_embeddings = _count_query(
            conn,
            """
            SELECT COUNT(*) FROM nodes n
            LEFT JOIN vec_node_map m ON m.node_id = n.id
            WHERE m.node_id IS NULL
            """,
        )

    report: dict[str, object] = dict(base)
    report["schema_version"] = schema_version
    report["integrity_check"] = integrity_result
    report["integrity_ok"] = integrity_ok
    report["vec_table_present"] = vec_table_present
    report["embeddings_model_available"] = embeddings_available()
    report["nodes_missing_embeddings"] = nodes_missing_embeddings
    report["is_healthy"] = bool(report["is_healthy"]) and integrity_ok
    return report


def get_current_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    return row[0] or 0 if row else 0


def apply_migrations(conn: sqlite3.Connection) -> None:
    current = get_current_version(conn)
    for version in sorted(MIGRATIONS):
        if version <= current:
            continue
        description, migration = MIGRATIONS[version]
        try:
            migration(conn)
            conn.execute(
                "INSERT INTO schema_version (version, applied_at, description) VALUES (?, ?, ?)",
                (version, utcnow_iso(), description),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise


__all__ = [
    "MIGRATIONS",
    "apply_migrations",
    "check_database_health",
    "datetime_to_iso",
    "get_connection",
    "get_current_version",
    "get_initialized_connection",
    "initialize",
    "iso_to_datetime",
    "resolve_workspace_id",
    "utcnow",
    "utcnow_iso",
]