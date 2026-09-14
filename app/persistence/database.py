from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Callable, Iterator

SCHEMA_VERSION = 5


class SQLiteDatabase:
    """Durable SQLite infrastructure with explicit tracked migrations."""

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
            connection.executescript(BASE_SCHEMA)
            row = connection.execute(
                "SELECT value FROM persistence_metadata WHERE key = 'schema_version'"
            ).fetchone()

            if row is None:
                connection.execute(
                    "INSERT INTO persistence_metadata(key, value) VALUES('schema_version', '1')"
                )
                current_version = 1
            else:
                try:
                    current_version = int(row[0])
                except (TypeError, ValueError) as exc:
                    raise RuntimeError("Invalid persistence schema version.") from exc

            if current_version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"Unsupported persistence schema version: {current_version}"
                )

            while current_version < SCHEMA_VERSION:
                migration = MIGRATIONS.get(current_version)
                if migration is None:
                    raise RuntimeError(
                        f"No migration registered from schema version {current_version}."
                    )
                connection.execute("BEGIN IMMEDIATE")
                try:
                    migration(connection)
                    current_version += 1
                    connection.execute(
                        "UPDATE persistence_metadata SET value = ? WHERE key = 'schema_version'",
                        (str(current_version),),
                    )
                except Exception:
                    connection.rollback()
                    raise
                else:
                    connection.commit()

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


BASE_SCHEMA = """
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


def _migrate_v1_to_v2(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS credentials (
            user_id TEXT PRIMARY KEY,
            credential_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS auth_throttle_state (
            throttle_key_hash TEXT PRIMARY KEY,
            failures INTEGER NOT NULL CHECK(failures >= 0),
            first_failure_at TEXT NOT NULL,
            blocked_until TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_auth_throttle_blocked_until ON auth_throttle_state(blocked_until)"
    )


def _migrate_v2_to_v3(connection: sqlite3.Connection) -> None:
    """
    Phase C WhatsApp identity and inbound-message persistence.

    Sender identifiers are stored only as keyed hashes. Provider message IDs
    are unique per provider/provider-account combination to provide durable
    replay protection.
    """
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS whatsapp_bindings (
            binding_id TEXT PRIMARY KEY,
            provider TEXT NOT NULL,
            provider_account_id TEXT NOT NULL,
            sender_id_hash TEXT NOT NULL,
            user_id TEXT NOT NULL,
            business_id TEXT NOT NULL,
            role TEXT NOT NULL,
            active INTEGER NOT NULL CHECK(active IN (0, 1)),
            FOREIGN KEY(user_id)
                REFERENCES users(user_id)
                ON DELETE CASCADE,
            FOREIGN KEY(business_id)
                REFERENCES businesses(business_id)
                ON DELETE CASCADE,
            UNIQUE(provider, provider_account_id, sender_id_hash)
        )
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_whatsapp_bindings_business
        ON whatsapp_bindings(business_id)
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_whatsapp_bindings_user
        ON whatsapp_bindings(user_id)
        """
    )

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS whatsapp_inbound_messages (
            provider TEXT NOT NULL,
            provider_account_id TEXT NOT NULL,
            provider_message_id TEXT NOT NULL,
            sender_id_hash TEXT NOT NULL,
            status TEXT NOT NULL,
            received_at TEXT NOT NULL,
            completed_at TEXT,
            response_text TEXT,
            error_code TEXT,
            PRIMARY KEY(
                provider,
                provider_account_id,
                provider_message_id
            )
        )
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_whatsapp_messages_sender
        ON whatsapp_inbound_messages(sender_id_hash)
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_whatsapp_messages_status
        ON whatsapp_inbound_messages(status)
        """
    )


def _migrate_v3_to_v4(connection: sqlite3.Connection) -> None:
    """
    Phase C WhatsApp conversation persistence.

    Conversation history is scoped to the trusted WhatsApp binding so that
    separate users/customers of the same business cannot share history.
    """

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS whatsapp_conversation_turns (
            binding_id TEXT NOT NULL,
            business_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(binding_id, sequence),
            FOREIGN KEY(binding_id)
                REFERENCES whatsapp_bindings(binding_id)
                ON DELETE CASCADE,
            FOREIGN KEY(business_id)
                REFERENCES businesses(business_id)
                ON DELETE CASCADE,
            CHECK(sequence > 0),
            CHECK(role IN ('user', 'assistant')),
            CHECK(length(content) > 0)
        )
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_whatsapp_conversation_business_binding
        ON whatsapp_conversation_turns(
            business_id,
            binding_id,
            sequence
        )
        """
    )


def _migrate_v4_to_v5(connection: sqlite3.Connection) -> None:
    """
    Harden WhatsApp delivery durability.

    Existing v4 rows are retained. New delivery metadata is nullable so
    historical records remain readable and migration is non-destructive.
    """

    columns = {
        row["name"]
        for row in connection.execute(
            "PRAGMA table_info(whatsapp_inbound_messages)"
        ).fetchall()
    }

    additions = {
        "business_id": "TEXT",
        "binding_id": "TEXT",
        "inbound_text": "TEXT",
        "delivery_attempted_at": "TEXT",
        "delivered_at": "TEXT",
        "conversation_persisted_at": "TEXT",
        "provider_response_message_id": "TEXT",
    }

    for name, definition in additions.items():
        if name not in columns:
            connection.execute(
                f"ALTER TABLE whatsapp_inbound_messages "
                f"ADD COLUMN {name} {definition}"
            )

    conversation_columns = {
        row["name"]
        for row in connection.execute(
            "PRAGMA table_info(whatsapp_conversation_turns)"
        ).fetchall()
    }

    if "exchange_id" not in conversation_columns:
        connection.execute(
            """
            ALTER TABLE whatsapp_conversation_turns
            ADD COLUMN exchange_id TEXT
            """
        )

    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS
        idx_whatsapp_conversation_exchange
        ON whatsapp_conversation_turns(binding_id, exchange_id)
        WHERE exchange_id IS NOT NULL
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_whatsapp_messages_delivery_state
        ON whatsapp_inbound_messages(status)
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_whatsapp_messages_business_binding
        ON whatsapp_inbound_messages(business_id, binding_id)
        """
    )

MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {
    1: _migrate_v1_to_v2,
    2: _migrate_v2_to_v3,
    3: _migrate_v3_to_v4,
    4: _migrate_v4_to_v5,
}

# Backwards-compatible name for callers that imported SCHEMA.
SCHEMA = BASE_SCHEMA
