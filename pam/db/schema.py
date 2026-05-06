from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from config import DB_PATH


CONNECTION_PRAGMAS = (
    "PRAGMA journal_mode = WAL",
    "PRAGMA foreign_keys = ON",
    "PRAGMA busy_timeout = 5000",
)


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
    return conn


def get_initialized_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    conn = get_connection(db_path)
    initialize(conn)
    return conn


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


MIGRATIONS = {
    1: ("Initial schema — nodes, edges, fts_index, triggers", migrate_v1),
}


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}


def _ensure_schema_compatibility(conn: sqlite3.Connection) -> None:
    node_columns = _table_columns(conn, "nodes")
    if "workspace_id" not in node_columns:
        conn.execute("ALTER TABLE nodes ADD COLUMN workspace_id TEXT NOT NULL DEFAULT ''")

    conn.execute("CREATE INDEX IF NOT EXISTS idx_nodes_workspace_id ON nodes(workspace_id)")
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