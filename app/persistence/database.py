from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Iterator

SCHEMA_VERSION = 1


class SQLiteDatabase:
    """Durable SQLite infrastructure boundary.

    Application code depends on repository/transaction contracts rather than
    SQLite directly. SQLite is the first concrete durable adapter because it
    is provided by Python's standard library; a future PostgreSQL adapter can
    replace this layer without changing domain contracts.
    """

    def __init__(self, path: str | Path) -> None:
        if not isinstance(path, (str, Path)):
            raise TypeError("path must be a string or Path.")
        self._path = Path(path)
        if not str(self._path).strip():
            raise ValueError("path must be non-empty.")

    @property
    def path(self) -> Path:
        return self._path

    def initialize(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as connection:
            connection.executescript(SCHEMA)
            row = connection.execute(
                "SELECT value FROM persistence_metadata WHERE key = 'schema_version'"
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO persistence_metadata(key, value) VALUES('schema_version', ?)",
                    (str(SCHEMA_VERSION),),
                )
            elif int(row[0]) != SCHEMA_VERSION:
                raise RuntimeError(
                    f"Unsupported persistence schema version: {row[0]}"
                )

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            self._path,
            timeout=10.0,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except Exception:
                connection.rollback()
                raise
            else:
                connection.commit()


SCHEMA = """
CREATE TABLE IF NOT EXISTS persistence_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS businesses (
    business_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    owner_name TEXT NOT NULL,
    assistant_name TEXT NOT NULL,
    assistant_voice TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    email TEXT NOT NULL COLLATE NOCASE UNIQUE
);

CREATE TABLE IF NOT EXISTS business_memberships (
    user_id TEXT NOT NULL,
    business_id TEXT NOT NULL,
    role TEXT NOT NULL,
    PRIMARY KEY(user_id, business_id),
    FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY(business_id) REFERENCES businesses(business_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    business_id TEXT NOT NULL,
    role TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    revoked_at TEXT,
    FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY(business_id) REFERENCES businesses(business_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_business ON sessions(business_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);

CREATE TABLE IF NOT EXISTS memories (
    memory_id TEXT PRIMARY KEY,
    business_id TEXT NOT NULL,
    content TEXT NOT NULL,
    memory_type TEXT NOT NULL,
    importance INTEGER NOT NULL CHECK(importance BETWEEN 1 AND 5),
    FOREIGN KEY(business_id) REFERENCES businesses(business_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_memories_business ON memories(business_id);

CREATE TABLE IF NOT EXISTS business_trials (
    business_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    FOREIGN KEY(business_id) REFERENCES businesses(business_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS commercial_states (
    business_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    FOREIGN KEY(business_id) REFERENCES businesses(business_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS purchase_records (
    provider TEXT NOT NULL,
    provider_event_id TEXT NOT NULL,
    business_id TEXT NOT NULL,
    amount TEXT NOT NULL,
    currency TEXT NOT NULL,
    paid_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    PRIMARY KEY(provider, provider_event_id),
    FOREIGN KEY(business_id) REFERENCES businesses(business_id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_purchase_business ON purchase_records(business_id);

CREATE TABLE IF NOT EXISTS paid_business_ledger (
    business_id TEXT PRIMARY KEY,
    FOREIGN KEY(business_id) REFERENCES businesses(business_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS launch_program (
    singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
    target_businesses INTEGER NOT NULL CHECK(target_businesses > 0),
    paid_businesses INTEGER NOT NULL CHECK(paid_businesses >= 0 AND paid_businesses <= target_businesses)
);
INSERT OR IGNORE INTO launch_program(singleton_id, target_businesses, paid_businesses)
VALUES(1, 10, 0);
"""
