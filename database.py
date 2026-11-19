"""
database.py — Thin SQLite layer.

A connection is opened per operation (cheap for a local, single-user app) so the
same module works from FastAPI's thread pool and from the stdlib fallback server
without cross-thread weirdness.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from typing import Any, Iterable, Iterator, Sequence

import config
import models


# --------------------------------------------------------------------------- #
# Time helpers (local time — the diary is a personal, local-first tool)
# --------------------------------------------------------------------------- #
def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def today_iso() -> str:
    return date.today().isoformat()


# --------------------------------------------------------------------------- #
# Connections
# --------------------------------------------------------------------------- #
def _configure(conn: sqlite3.Connection) -> None:
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """Open a connection; commits on success, rolls back on error."""
    config.ensure_data_dir()
    conn = sqlite3.connect(str(config.DB_PATH), timeout=10.0)
    try:
        _configure(conn)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    """Alias kept for readability at call sites that write several rows."""
    with connect() as conn:
        yield conn


# --------------------------------------------------------------------------- #
# Query helpers
# --------------------------------------------------------------------------- #
def fetch_all(sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
    with connect() as conn:
        return list(conn.execute(sql, tuple(params)).fetchall())


def fetch_one(sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute(sql, tuple(params)).fetchone()


def fetch_value(sql: str, params: Sequence[Any] = (), default: Any = None) -> Any:
    row = fetch_one(sql, params)
    if row is None:
        return default
    value = row[0]
    return default if value is None else value


def execute(sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
    """Run a write statement and return the cursor (``lastrowid`` / ``rowcount``)."""
    with connect() as conn:
        return conn.execute(sql, tuple(params))


def insert(sql: str, params: Sequence[Any] = ()) -> int:
    with connect() as conn:
        cur = conn.execute(sql, tuple(params))
        return int(cur.lastrowid or 0)


def execute_many(sql: str, rows: Iterable[Sequence[Any]]) -> int:
    rows = list(rows)
    if not rows:
        return 0
    with connect() as conn:
        cur = conn.executemany(sql, rows)
        return cur.rowcount


# --------------------------------------------------------------------------- #
# Schema lifecycle
# --------------------------------------------------------------------------- #
def init_db() -> None:
    """Create tables and indexes if they do not exist yet (idempotent)."""
    config.ensure_data_dir()
    with connect() as conn:
        for statement in models.SCHEMA_SQL:
            conn.execute(statement)
        for statement in models.INDEX_SQL:
            conn.execute(statement)


def is_empty() -> bool:
    """True when no profile has been created yet (i.e. the DB needs seeding)."""
    try:
        return int(fetch_value(f"SELECT COUNT(*) FROM {models.PROFILES}", default=0)) == 0
    except sqlite3.OperationalError:
        return True


def drop_all() -> None:
    """Delete every table — used by ``seed_data.py --reset``."""
    with connect() as conn:
        for table in (
            models.MEDICATION_CHECKS, models.MEDICATION_INTAKES, models.HEADACHE_LOGS,
            models.SYMPTOM_LOGS, models.WATER_LOGS, models.MEAL_IDEAS, models.FOODS,
            models.MEDICATIONS, models.PROFILES, models.APP_SETTINGS,
        ):
            conn.execute(f"DROP TABLE IF EXISTS {table}")


# --------------------------------------------------------------------------- #
# Key/value settings
# --------------------------------------------------------------------------- #
def get_setting(key: str, default: str | None = None) -> str | None:
    row = fetch_one(f"SELECT value FROM {models.APP_SETTINGS} WHERE key = ?", (key,))
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    execute(
        f"INSERT INTO {models.APP_SETTINGS} (key, value) VALUES (?, ?) "
        f"ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def all_settings() -> dict[str, str]:
    return {row["key"]: row["value"] for row in fetch_all(f"SELECT key, value FROM {models.APP_SETTINGS}")}


def db_info() -> dict:
    """Small diagnostics block for the settings tab."""
    return {
        "path": str(config.DB_PATH),
        "exists": config.DB_PATH.exists(),
        "size_kb": round(config.DB_PATH.stat().st_size / 1024, 1) if config.DB_PATH.exists() else 0,
        "profiles": int(fetch_value(f"SELECT COUNT(*) FROM {models.PROFILES}", default=0) or 0),
        "foods": int(fetch_value(f"SELECT COUNT(*) FROM {models.FOODS}", default=0) or 0),
        "meal_ideas": int(fetch_value(f"SELECT COUNT(*) FROM {models.MEAL_IDEAS}", default=0) or 0),
    }
