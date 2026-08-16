"""
db.py — Database backend with automatic in-memory SQLite fallback.

Priority:
  1. PostgreSQL (production) — used when DATABASE_URL is reachable.
  2. SQLite :memory: (fallback) — used when PostgreSQL is unavailable at startup.

The public interface (`get_db_cursor`, `is_using_memory_db`) is backend-agnostic.
Callers should never need to know which backend is active.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Iterator, Optional, Tuple

from app.config import settings

# ---------------------------------------------------------------------------
# Backend state
# ---------------------------------------------------------------------------

_db_pool = None                   # psycopg2 pool (None when Postgres unavailable)
_sqlite_conn: Optional[sqlite3.Connection] = None
_sqlite_lock = threading.Lock()   # SQLite is not thread-safe without care
_backend: str = "none"            # "postgres" | "sqlite" | "none"


# ---------------------------------------------------------------------------
# PostgreSQL helpers
# ---------------------------------------------------------------------------

def _try_init_postgres(minconn: int = 1, maxconn: int = 8) -> bool:
    global _db_pool, _backend
    try:
        from psycopg2 import pool as pg_pool
        _db_pool = pg_pool.SimpleConnectionPool(
            minconn=minconn,
            maxconn=maxconn,
            dsn=settings.DATABASE_URL,
            connect_timeout=3,        # fail fast — don't block startup
        )
        _backend = "postgres"
        print("[DB] Connected to PostgreSQL.")
        return True
    except Exception as exc:
        print(f"[DB] PostgreSQL unavailable ({exc}). Falling back to in-memory SQLite.")
        _db_pool = None
        return False


# ---------------------------------------------------------------------------
# SQLite in-memory helpers
# ---------------------------------------------------------------------------

def _init_sqlite() -> None:
    global _sqlite_conn, _backend
    # check_same_thread=False + external lock = safe for FastAPI thread pool
    
    # Use a persistent local file instead of :memory: so data isn't lost on restart
    import os
    db_path = os.path.join(os.path.dirname(__file__), "..", "skywatch.db")
    _sqlite_conn = sqlite3.connect(db_path, check_same_thread=False)
    
    _sqlite_conn.row_factory = sqlite3.Row   # dict-like rows
    _backend = "sqlite"
    _ensure_sqlite_schema(_sqlite_conn)
    print(f"[DB] Persistent SQLite database initialized at {db_path}")


def _ensure_sqlite_schema(conn: sqlite3.Connection) -> None:
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
            role     TEXT NOT NULL DEFAULT 'member'
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
            status     TEXT DEFAULT 'stopped',
            created_at REAL DEFAULT (strftime('%s','now')),
            updated_at REAL DEFAULT (strftime('%s','now'))
        );
    """)
    conn.commit()

    # Seed default admin (password: "admin") if not present
    try:
        from app.utils.security import hash_password
        cur.execute("SELECT id FROM users WHERE username = ?", ("admin",))
        if not cur.fetchone():
            cur.execute(
                "INSERT INTO users (username, hashed_password, role) VALUES (?, ?, ?)",
                ("admin", hash_password("admin"), "admin"),
            )
            conn.commit()
    except Exception as exc:
        print(f"[DB] Warning: could not seed SQLite admin user: {exc}")



class _SqliteRealDictRow(dict):
    """Thin wrapper so callers can do row["col"] transparently."""


class _SqliteCursorWrapper:
    """Wraps sqlite3.Cursor to provide a psycopg2-compatible API."""

    def __init__(self, cursor: sqlite3.Cursor):
        self._cur = cursor

    def execute(self, sql: str, params=()) -> None:
        # Convert %s placeholders (psycopg2-style) → ? (sqlite3-style)
        sql = _pg_to_sqlite_sql(sql)
        self._cur.execute(sql, params)

    def executemany(self, sql: str, seq_of_params) -> None:
        sql = _pg_to_sqlite_sql(sql)
        self._cur.executemany(sql, seq_of_params)

    def fetchall(self):
        rows = self._cur.fetchall()
        return [_row_to_dict(r) for r in rows]

    def fetchone(self):
        row = self._cur.fetchone()
        return _row_to_dict(row) if row else None

    def close(self):
        self._cur.close()

    @property
    def rowcount(self):
        return self._cur.rowcount


def _row_to_dict(row: sqlite3.Row) -> dict | None:
    if row is None:
        return None
    return dict(row)


def _pg_to_sqlite_sql(sql: str) -> str:
    """
    Best-effort conversion of PostgreSQL-flavoured SQL to SQLite-compatible SQL.
    Handles the specific patterns used by this codebase:
      - %s  →  ?
      - NOW()  →  datetime('now')
      - ON CONFLICT (id) DO UPDATE SET ...  →  INSERT OR REPLACE (handled at call site)
      - TO_TIMESTAMP / EXTRACT(EPOCH ...) / DOUBLE PRECISION  → SQLite equivalents
      - INTERVAL '1 second'  →  stripped (handled via plain arithmetic)
    """
    import re
    sql = sql.replace("%s", "?")
    sql = re.sub(r"\bNOW\(\)", "datetime('now')", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\bDOUBLE PRECISION\b", "REAL", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\bSERIAL\b", "INTEGER", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\bVARCHAR\(\d+\)\b", "TEXT", sql, flags=re.IGNORECASE)

    # TO_TIMESTAMP(FLOOR(EXTRACT(EPOCH FROM timestamp) / ?) * ?)
    # → datetime(CAST(CAST(timestamp AS INTEGER) / ? * ? AS INTEGER), 'unixepoch')
    sql = re.sub(
        r"TO_TIMESTAMP\(\s*FLOOR\(\s*EXTRACT\(\s*EPOCH\s+FROM\s+(\w+)\s*\)\s*/\s*\?\s*\)\s*\*\s*\?\s*\)",
        r"datetime(CAST(CAST(\1 AS INTEGER) / ? * ? AS INTEGER), 'unixepoch')",
        sql,
        flags=re.IGNORECASE,
    )
    # EXTRACT(EPOCH FROM col)  →  col (already a unix timestamp in SQLite)
    sql = re.sub(r"EXTRACT\(\s*EPOCH\s+FROM\s+(\w+)\s*\)", r"\1", sql, flags=re.IGNORECASE)
    # NOW() - (? * INTERVAL '1 second')  →  datetime('now', '-' || ? || ' seconds')
    sql = re.sub(
        r"NOW\(\)\s*-\s*\(\s*\?\s*\*\s*INTERVAL\s*'1 second'\s*\)",
        "unixepoch() - ?",
        sql,
        flags=re.IGNORECASE,
    )
    # ::DOUBLE PRECISION, ::TEXT, etc.   (PostgreSQL cast shorthand)
    sql = re.sub(r"::\w+", "", sql)
    # ON CONFLICT ... DO UPDATE  →  OR REPLACE (handled via INSERT OR REPLACE below)
    sql = re.sub(r"\s+ON\s+CONFLICT\s*\(.*?\)\s*DO\s+UPDATE\s+SET[\s\S]*", "", sql, flags=re.IGNORECASE)
    return sql


class _SqliteConnWrapper:
    """Stub that satisfies the (conn, cursor) tuple contract."""
    def rollback(self): pass
    def commit(self): pass


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_using_memory_db() -> bool:
    """Return True when the SQLite in-memory fallback is active."""
    return _backend == "sqlite"


def init_db_pool(minconn: int = 1, maxconn: int = 8) -> None:
    global _backend
    if _backend != "none":
        return   # already initialized

    if not _try_init_postgres(minconn, maxconn):
        _init_sqlite()


def close_db_pool() -> None:
    global _db_pool, _sqlite_conn, _backend
    if _db_pool is not None:
        _db_pool.closeall()
        _db_pool = None
    if _sqlite_conn is not None:
        _sqlite_conn.close()
        _sqlite_conn = None
    _backend = "none"


def ensure_schema() -> None:
    """Create tables if they don't exist (only needed for PostgreSQL)."""
    if _backend == "sqlite":
        return   # schema already created in _init_sqlite()

    if _backend == "postgres" and _db_pool is not None:
        conn = _db_pool.getconn()
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS drones (
                    id            VARCHAR(50) PRIMARY KEY,
                    name          TEXT NOT NULL,
                    latitude      DOUBLE PRECISION NOT NULL DEFAULT 0,
                    longitude     DOUBLE PRECISION NOT NULL DEFAULT 0,
                    altitude      DOUBLE PRECISION NOT NULL DEFAULT 0,
                    battery_level DOUBLE PRECISION DEFAULT 100,
                    is_active     BOOLEAN DEFAULT TRUE,
                    feed_url      TEXT,
                    updated_at    TIMESTAMP DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS density_records (
                    id            SERIAL PRIMARY KEY,
                    drone_id      VARCHAR(50) REFERENCES drones(id),
                    latitude      DOUBLE PRECISION NOT NULL,
                    longitude     DOUBLE PRECISION NOT NULL,
                    person_count  INTEGER DEFAULT 0,
                    density_level DOUBLE PRECISION DEFAULT 0.0,
                    timestamp     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_density_timestamp ON density_records (timestamp DESC)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_density_drone_timestamp ON density_records (drone_id, timestamp DESC)")

            # ── Users table (auth) ─────────────────────────────────────────
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id              SERIAL PRIMARY KEY,
                    username        VARCHAR(100) UNIQUE NOT NULL,
                    hashed_password TEXT NOT NULL,
                    role            VARCHAR(20) NOT NULL DEFAULT 'member',
                    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Seed default admin on first run (password: "admin")
            # We import here to avoid a circular import at module level.
            try:
                from app.utils.security import hash_password
                cur.execute(
                    """
                    INSERT INTO users (username, hashed_password, role)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (username) DO NOTHING
                    """,
                    ("admin", hash_password("admin"), "admin"),
                )
            except Exception as seed_exc:
                print(f"[DB] Warning: could not seed admin user: {seed_exc}")

            cur.execute("""
                CREATE TABLE IF NOT EXISTS drone_configs (
                    drone_id   VARCHAR(50) PRIMARY KEY,
                    drone_name VARCHAR(100) NOT NULL,
                    source     TEXT NOT NULL,
                    latitude   DOUBLE PRECISION NOT NULL,
                    longitude  DOUBLE PRECISION NOT NULL,
                    altitude   DOUBLE PRECISION DEFAULT 100.0,
                    zone       VARCHAR(200) DEFAULT 'Live Stream Zone',
                    fps        INTEGER DEFAULT 5,
                    loop       BOOLEAN DEFAULT FALSE,
                    model      VARCHAR(50) DEFAULT 'sdnet',
                    device     VARCHAR(50) DEFAULT 'cpu',
                    status     VARCHAR(20) DEFAULT 'stopped',
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """)

            conn.commit()
            cur.close()
        finally:
            _db_pool.putconn(conn)



@contextmanager
def get_db_cursor(dict_rows: bool = False) -> Iterator[Tuple[object, object]]:
    """
    Yields (conn, cursor). Works for both PostgreSQL and SQLite backends.
    Always prefer this context manager over raw connections.
    """
    if _backend == "none":
        raise RuntimeError("Database not initialized. Call init_db_pool() first.")

    if _backend == "postgres":
        yield from _postgres_cursor(dict_rows)
    else:
        yield from _sqlite_cursor()


def _postgres_cursor(dict_rows: bool):
    from psycopg2.extras import RealDictCursor
    conn = _db_pool.getconn()
    cursor = None
    try:
        cursor_factory = RealDictCursor if dict_rows else None
        cursor = conn.cursor(cursor_factory=cursor_factory)
        yield conn, cursor
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        if cursor is not None:
            cursor.close()
        _db_pool.putconn(conn)


def _sqlite_cursor():
    with _sqlite_lock:
        conn_stub = _SqliteConnWrapper()
        raw_cur = _sqlite_conn.cursor()
        cursor = _SqliteCursorWrapper(raw_cur)
        try:
            yield conn_stub, cursor
            _sqlite_conn.commit()
        except Exception:
            _sqlite_conn.rollback()
            raise
        finally:
            cursor.close()
