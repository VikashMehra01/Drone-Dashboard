"""
db.py — SQLite database access.

SkyWatch uses a single local SQLite file (backend/skywatch.db) as its only
database. No external database server or Docker container is required —
the file is created and its schema initialized automatically on backend
startup.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from typing import Iterator, Optional, Tuple

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "skywatch.db")

_conn: Optional[sqlite3.Connection] = None
_lock = threading.Lock()   # SQLite is not thread-safe without care


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

def init_db_pool() -> None:
    """Open the SQLite connection and ensure the schema exists. Idempotent."""
    global _conn
    if _conn is not None:
        return

    # check_same_thread=False + external lock = safe for FastAPI's thread pool
    _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    _ensure_schema(_conn)
    print(f"[DB] SQLite database ready at {DB_PATH}")


def close_db_pool() -> None:
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None


def ensure_schema() -> None:
    """No-op — schema is created by init_db_pool(). Kept so app/main.py's
    startup hook doesn't need to know that detail."""
    return


def _ensure_schema(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS drones (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            latitude    REAL NOT NULL DEFAULT 0.0,
            longitude   REAL NOT NULL DEFAULT 0.0,
            altitude    REAL NOT NULL DEFAULT 0.0,
            battery_level REAL DEFAULT 100.0,
            is_active   INTEGER DEFAULT 1,
            feed_url    TEXT,
            updated_at  REAL DEFAULT (julianday('now'))
        );

        CREATE TABLE IF NOT EXISTS density_records (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            drone_id      TEXT REFERENCES drones(id),
            latitude      REAL NOT NULL,
            longitude     REAL NOT NULL,
            person_count  INTEGER DEFAULT 0,
            density_level REAL DEFAULT 0.0,
            timestamp     REAL DEFAULT (strftime('%s', 'now'))
        );

        CREATE INDEX IF NOT EXISTS idx_density_timestamp
            ON density_records (timestamp DESC);

        CREATE INDEX IF NOT EXISTS idx_density_drone_timestamp
            ON density_records (drone_id, timestamp DESC);

        CREATE TABLE IF NOT EXISTS users (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            hashed_password TEXT NOT NULL,
            role     TEXT NOT NULL DEFAULT 'member',
            created_at REAL DEFAULT (strftime('%s','now'))
        );

        CREATE TABLE IF NOT EXISTS drone_configs (
            drone_id   TEXT PRIMARY KEY,
            drone_name TEXT NOT NULL,
            source     TEXT NOT NULL,
            latitude   REAL NOT NULL,
            longitude  REAL NOT NULL,
            altitude   REAL DEFAULT 100.0,
            zone       TEXT DEFAULT 'Live Stream Zone',
            fps        INTEGER DEFAULT 5,
            loop       INTEGER DEFAULT 0,
            model      TEXT DEFAULT 'sdnet',
            device     TEXT DEFAULT 'cpu',
            pid        INTEGER,
            status     TEXT DEFAULT 'stopped',
            created_at REAL DEFAULT (strftime('%s','now')),
            updated_at REAL DEFAULT (strftime('%s','now'))
        );
    """)
    conn.commit()

    # Migrations: add columns that predate CREATE TABLE IF NOT EXISTS additions
    # (a no-op on an already-current table).
    drone_config_cols = {row[1] for row in cur.execute("PRAGMA table_info(drone_configs)").fetchall()}
    if "pid" not in drone_config_cols:
        cur.execute("ALTER TABLE drone_configs ADD COLUMN pid INTEGER")
        conn.commit()

    user_cols = {row[1] for row in cur.execute("PRAGMA table_info(users)").fetchall()}
    if "created_at" not in user_cols:
        cur.execute("ALTER TABLE users ADD COLUMN created_at REAL DEFAULT (strftime('%s','now'))")
        conn.commit()

    # Seed default admin (password: "admin") if not present
    from app.utils.security import hash_password
    cur.execute("SELECT id FROM users WHERE username = ?", ("admin",))
    if not cur.fetchone():
        cur.execute(
            "INSERT INTO users (username, hashed_password, role) VALUES (?, ?, ?)",
            ("admin", hash_password("admin"), "admin"),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Cursor access
# ---------------------------------------------------------------------------

class _DictCursor:
    """Thin wrapper so fetchall()/fetchone() return plain dicts (row["col"]
    *and* row.get("col") both work) instead of raw sqlite3.Row objects."""

    def __init__(self, cursor: sqlite3.Cursor):
        self._cur = cursor

    def execute(self, sql: str, params=()) -> None:
        self._cur.execute(sql, params)

    def executemany(self, sql: str, seq_of_params) -> None:
        self._cur.executemany(sql, seq_of_params)

    def fetchall(self) -> list[dict]:
        return [dict(row) for row in self._cur.fetchall()]

    def fetchone(self) -> Optional[dict]:
        row = self._cur.fetchone()
        return dict(row) if row is not None else None

    def close(self) -> None:
        self._cur.close()

    @property
    def rowcount(self) -> int:
        return self._cur.rowcount


@contextmanager
def get_db_cursor(dict_rows: bool = True) -> Iterator[Tuple[sqlite3.Connection, _DictCursor]]:
    """Yields (conn, cursor). Rows are always returned as plain dicts
    (`dict_rows` is accepted for call-site compatibility but has no effect)."""
    if _conn is None:
        raise RuntimeError("Database not initialized. Call init_db_pool() first.")

    with _lock:
        cursor = _DictCursor(_conn.cursor())
        try:
            yield _conn, cursor
            _conn.commit()
        except Exception:
            _conn.rollback()
            raise
        finally:
            cursor.close()
