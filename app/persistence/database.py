from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Callable, Iterator

SCHEMA_VERSION = 21


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


def _migrate_v5_to_v6(connection: sqlite3.Connection) -> None:
    """Add explicit platform-level Founder authority."""

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS platform_founders (
            user_id TEXT PRIMARY KEY,
            active INTEGER NOT NULL DEFAULT 1
                CHECK(active IN (0, 1)),
            FOREIGN KEY(user_id)
                REFERENCES users(user_id)
                ON DELETE RESTRICT
        )
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_platform_founders_active
        ON platform_founders(active)
        """
    )


def _migrate_v6_to_v7(connection: sqlite3.Connection) -> None:
    """Add the append-only platform event evidence foundation."""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS platform_events (
            event_id TEXT PRIMARY KEY,
            occurred_at TEXT NOT NULL,
            event_type TEXT NOT NULL,
            business_id TEXT,
            user_id TEXT,
            channel TEXT NOT NULL,
            actor_type TEXT NOT NULL,
            action TEXT NOT NULL,
            outcome TEXT NOT NULL,
            correlation_id TEXT NOT NULL,
            metadata TEXT NOT NULL
        )
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_platform_events_business_time
        ON platform_events(business_id, occurred_at DESC)
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_platform_events_user_time
        ON platform_events(user_id, occurred_at DESC)
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_platform_events_type_time
        ON platform_events(event_type, occurred_at DESC)
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_platform_events_correlation
        ON platform_events(correlation_id)
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_platform_events_outcome_time
        ON platform_events(outcome, occurred_at DESC)
        """
    )

    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS platform_events_no_update
        BEFORE UPDATE ON platform_events
        BEGIN
            SELECT RAISE(
                ABORT,
                'platform_events are append-only'
            );
        END
        """
    )

    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS platform_events_no_delete
        BEFORE DELETE ON platform_events
        BEGIN
            SELECT RAISE(
                ABORT,
                'platform_events are append-only'
            );
        END
        """
    )


def _migrate_v7_to_v8(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE safety_incidents (
            incident_id TEXT PRIMARY KEY,
            status TEXT NOT NULL
                CHECK(status IN (
                    'open',
                    'investigating',
                    'resolved',
                    'verified',
                    'resume_authorized',
                    'closed'
                )),
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL,
            created_by_user_id TEXT NOT NULL,
            resolved_at TEXT,
            resolved_by_user_id TEXT,
            verification_notes TEXT,
            verified_at TEXT,
            verified_by_user_id TEXT,
            resume_authorized_at TEXT,
            resume_authorized_by_user_id TEXT,
            closed_at TEXT,
            closed_by_user_id TEXT,

            FOREIGN KEY(created_by_user_id)
                REFERENCES users(user_id)
                ON DELETE RESTRICT,

            FOREIGN KEY(resolved_by_user_id)
                REFERENCES users(user_id)
                ON DELETE RESTRICT,

            FOREIGN KEY(verified_by_user_id)
                REFERENCES users(user_id)
                ON DELETE RESTRICT,

            FOREIGN KEY(resume_authorized_by_user_id)
                REFERENCES users(user_id)
                ON DELETE RESTRICT,

            FOREIGN KEY(closed_by_user_id)
                REFERENCES users(user_id)
                ON DELETE RESTRICT,

            CHECK(
                status = 'open'
                OR (
                    resolved_at IS NOT NULL
                    AND resolved_by_user_id IS NOT NULL
                )
            ),

            CHECK(
                status NOT IN ('verified', 'resume_authorized', 'closed')
                OR (
                    verified_at IS NOT NULL
                    AND verified_by_user_id IS NOT NULL
                )
            ),

            CHECK(
                status NOT IN ('resume_authorized', 'closed')
                OR (
                    resume_authorized_at IS NOT NULL
                    AND resume_authorized_by_user_id IS NOT NULL
                )
            ),

            CHECK(
                status <> 'closed'
                OR (
                    closed_at IS NOT NULL
                    AND closed_by_user_id IS NOT NULL
                )
            )
        );

        CREATE INDEX idx_safety_incidents_status_time
            ON safety_incidents(status, created_at);

        CREATE INDEX idx_safety_incidents_creator_time
            ON safety_incidents(created_by_user_id, created_at);

        CREATE TABLE safety_controls (
            control_id TEXT PRIMARY KEY,
            scope TEXT NOT NULL
                CHECK(scope IN (
                    'global',
                    'business',
                    'capability',
                    'channel',
                    'integration'
                )),
            target TEXT NOT NULL,
            state TEXT NOT NULL
                CHECK(state IN ('active', 'halted')),
            reason TEXT NOT NULL,
            activated_at TEXT NOT NULL,
            activated_by_user_id TEXT NOT NULL,
            incident_id TEXT,
            resolved_at TEXT,
            resolved_by_user_id TEXT,
            resumed_at TEXT,
            resumed_by_user_id TEXT,

            FOREIGN KEY(activated_by_user_id)
                REFERENCES users(user_id)
                ON DELETE RESTRICT,

            FOREIGN KEY(resolved_by_user_id)
                REFERENCES users(user_id)
                ON DELETE RESTRICT,

            FOREIGN KEY(resumed_by_user_id)
                REFERENCES users(user_id)
                ON DELETE RESTRICT,

            FOREIGN KEY(incident_id)
                REFERENCES safety_incidents(incident_id)
                ON DELETE RESTRICT,

            CHECK(
                state = 'halted'
                OR (
                    resolved_at IS NOT NULL
                    AND resolved_by_user_id IS NOT NULL
                    AND resumed_at IS NOT NULL
                    AND resumed_by_user_id IS NOT NULL
                )
            )
        );

        CREATE UNIQUE INDEX idx_safety_controls_active_target
            ON safety_controls(scope, target)
            WHERE state = 'halted';

        CREATE INDEX idx_safety_controls_scope_target_state
            ON safety_controls(scope, target, state);

        CREATE INDEX idx_safety_controls_incident
            ON safety_controls(incident_id);
        """
    )




def _migrate_v8_to_v9(connection: sqlite3.Connection) -> None:
    """
    Rebuild the D5 safety tables with database constraints that match
    the intended incident recovery lifecycle.

    Existing safety incidents and controls are preserved.
    """

    connection.executescript(
        """
        CREATE TABLE safety_incidents_v9 (
            incident_id TEXT PRIMARY KEY,
            status TEXT NOT NULL
                CHECK(status IN (
                    'open',
                    'investigating',
                    'resolved',
                    'verified',
                    'resume_authorized',
                    'closed'
                )),
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL,
            created_by_user_id TEXT NOT NULL,
            resolved_at TEXT,
            resolved_by_user_id TEXT,
            verification_notes TEXT,
            verified_at TEXT,
            verified_by_user_id TEXT,
            resume_authorized_at TEXT,
            resume_authorized_by_user_id TEXT,
            closed_at TEXT,
            closed_by_user_id TEXT,

            FOREIGN KEY(created_by_user_id)
                REFERENCES users(user_id)
                ON DELETE RESTRICT,

            FOREIGN KEY(resolved_by_user_id)
                REFERENCES users(user_id)
                ON DELETE RESTRICT,

            FOREIGN KEY(verified_by_user_id)
                REFERENCES users(user_id)
                ON DELETE RESTRICT,

            FOREIGN KEY(resume_authorized_by_user_id)
                REFERENCES users(user_id)
                ON DELETE RESTRICT,

            FOREIGN KEY(closed_by_user_id)
                REFERENCES users(user_id)
                ON DELETE RESTRICT,

            CHECK(
                status IN ('open', 'investigating')
                OR (
                    resolved_at IS NOT NULL
                    AND resolved_by_user_id IS NOT NULL
                )
            ),

            CHECK(
                status NOT IN (
                    'verified',
                    'resume_authorized',
                    'closed'
                )
                OR (
                    resolved_at IS NOT NULL
                    AND resolved_by_user_id IS NOT NULL
                    AND verified_at IS NOT NULL
                    AND verified_by_user_id IS NOT NULL
                )
            ),

            CHECK(
                status NOT IN (
                    'resume_authorized',
                    'closed'
                )
                OR (
                    resolved_at IS NOT NULL
                    AND resolved_by_user_id IS NOT NULL
                    AND verified_at IS NOT NULL
                    AND verified_by_user_id IS NOT NULL
                    AND resume_authorized_at IS NOT NULL
                    AND resume_authorized_by_user_id IS NOT NULL
                )
            ),

            CHECK(
                status <> 'closed'
                OR (
                    resolved_at IS NOT NULL
                    AND resolved_by_user_id IS NOT NULL
                    AND verified_at IS NOT NULL
                    AND verified_by_user_id IS NOT NULL
                    AND resume_authorized_at IS NOT NULL
                    AND resume_authorized_by_user_id IS NOT NULL
                    AND closed_at IS NOT NULL
                    AND closed_by_user_id IS NOT NULL
                )
            )
        );

        INSERT INTO safety_incidents_v9 (
            incident_id,
            status,
            reason,
            created_at,
            created_by_user_id,
            resolved_at,
            resolved_by_user_id,
            verification_notes,
            verified_at,
            verified_by_user_id,
            resume_authorized_at,
            resume_authorized_by_user_id,
            closed_at,
            closed_by_user_id
        )
        SELECT
            incident_id,
            status,
            reason,
            created_at,
            created_by_user_id,
            resolved_at,
            resolved_by_user_id,
            verification_notes,
            verified_at,
            verified_by_user_id,
            resume_authorized_at,
            resume_authorized_by_user_id,
            closed_at,
            closed_by_user_id
        FROM safety_incidents;

        CREATE TABLE safety_controls_v9 (
            control_id TEXT PRIMARY KEY,
            scope TEXT NOT NULL
                CHECK(scope IN (
                    'global',
                    'business',
                    'capability',
                    'channel',
                    'integration'
                )),
            target TEXT NOT NULL,
            state TEXT NOT NULL
                CHECK(state IN ('active', 'halted')),
            reason TEXT NOT NULL,
            activated_at TEXT NOT NULL,
            activated_by_user_id TEXT NOT NULL,
            incident_id TEXT,
            resolved_at TEXT,
            resolved_by_user_id TEXT,
            resumed_at TEXT,
            resumed_by_user_id TEXT,

            FOREIGN KEY(activated_by_user_id)
                REFERENCES users(user_id)
                ON DELETE RESTRICT,

            FOREIGN KEY(resolved_by_user_id)
                REFERENCES users(user_id)
                ON DELETE RESTRICT,

            FOREIGN KEY(resumed_by_user_id)
                REFERENCES users(user_id)
                ON DELETE RESTRICT,

            FOREIGN KEY(incident_id)
                REFERENCES safety_incidents_v9(incident_id)
                ON DELETE RESTRICT,

            CHECK(
                state = 'halted'
                OR (
                    resolved_at IS NOT NULL
                    AND resolved_by_user_id IS NOT NULL
                    AND resumed_at IS NOT NULL
                    AND resumed_by_user_id IS NOT NULL
                )
            )
        );

        INSERT INTO safety_controls_v9 (
            control_id,
            scope,
            target,
            state,
            reason,
            activated_at,
            activated_by_user_id,
            incident_id,
            resolved_at,
            resolved_by_user_id,
            resumed_at,
            resumed_by_user_id
        )
        SELECT
            control_id,
            scope,
            target,
            state,
            reason,
            activated_at,
            activated_by_user_id,
            incident_id,
            resolved_at,
            resolved_by_user_id,
            resumed_at,
            resumed_by_user_id
        FROM safety_controls;

        DROP TABLE safety_controls;
        DROP TABLE safety_incidents;

        ALTER TABLE safety_incidents_v9
            RENAME TO safety_incidents;

        ALTER TABLE safety_controls_v9
            RENAME TO safety_controls;

        CREATE INDEX idx_safety_incidents_status_time
            ON safety_incidents(status, created_at);

        CREATE INDEX idx_safety_incidents_creator_time
            ON safety_incidents(created_by_user_id, created_at);

        CREATE UNIQUE INDEX idx_safety_controls_active_target
            ON safety_controls(scope, target)
            WHERE state = 'halted';

        CREATE INDEX idx_safety_controls_scope_target_state
            ON safety_controls(scope, target, state);

        CREATE INDEX idx_safety_controls_incident
            ON safety_controls(incident_id);
        """
    )


def _migrate_v9_to_v10(connection: sqlite3.Connection) -> None:
    """Add explicit BUSINESS/PLATFORM scope to durable sessions.

    Existing v9 sessions were necessarily business-scoped, so every migrated
    row receives BUSINESS scope while preserving its tenant and role data.
    The rebuilt table enforces valid scope combinations at the database
    boundary.
    """
    connection.executescript(
        """
        CREATE TABLE sessions_v10 (
            session_id_hash TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            scope TEXT NOT NULL
                CHECK(scope IN ('business', 'platform')),
            business_id TEXT,
            role TEXT,

            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            revoked_at TEXT,

            FOREIGN KEY(user_id)
                REFERENCES users(user_id)
                ON DELETE CASCADE,

            FOREIGN KEY(business_id)
                REFERENCES businesses(business_id)
                ON DELETE CASCADE,

            CHECK(
                (
                    scope = 'business'
                    AND business_id IS NOT NULL
                    AND role IN ('owner', 'admin', 'member')
                )
                OR
                (
                    scope = 'platform'
                    AND business_id IS NULL
                    AND role IS NULL
                )
            )
        );

        INSERT INTO sessions_v10 (
            session_id_hash,
            user_id,
            scope,
            business_id,
            role,
            created_at,
            expires_at,
            last_seen_at,
            revoked_at
        )
        SELECT
            session_id_hash,
            user_id,
            'business',
            business_id,
            role,
            created_at,
            expires_at,
            last_seen_at,
            revoked_at
        FROM sessions;

        DROP TABLE sessions;

        ALTER TABLE sessions_v10
            RENAME TO sessions;

        CREATE INDEX idx_sessions_user
            ON sessions(user_id);

        CREATE INDEX idx_sessions_business
            ON sessions(business_id);

        CREATE INDEX idx_sessions_expires
            ON sessions(expires_at);
        """
    )

def _migrate_v10_to_v11(connection: sqlite3.Connection) -> None:
    """
    Add durable, single-use capability confirmation records.

    Confirmation records bind one exact prepared capability execution to
    the authenticated session, user, business, and role that created it.
    The table deliberately stores the trusted execution payload rather
    than an AI proposal.
    """
    connection.executescript(
        """
        CREATE TABLE capability_confirmations (
            confirmation_id TEXT PRIMARY KEY,
            session_id_hash TEXT NOT NULL,
            user_id TEXT NOT NULL,
            business_id TEXT NOT NULL,
            role TEXT NOT NULL
                CHECK(role IN ('owner', 'admin', 'member')),
            capability TEXT NOT NULL,
            operation TEXT NOT NULL,
            arguments_json TEXT NOT NULL,
            reason TEXT NOT NULL,
            channel TEXT,
            integration TEXT,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            consumed_at TEXT,
            revoked_at TEXT,
            FOREIGN KEY(user_id)
                REFERENCES users(user_id)
                ON DELETE CASCADE,
            FOREIGN KEY(business_id)
                REFERENCES businesses(business_id)
                ON DELETE CASCADE,
            CHECK(length(confirmation_id) > 0),
            CHECK(length(session_id_hash) > 0),
            CHECK(length(user_id) > 0),
            CHECK(length(business_id) > 0),
            CHECK(length(capability) > 0),
            CHECK(length(operation) > 0),
            CHECK(length(arguments_json) > 0),
            CHECK(length(reason) > 0),
            CHECK(expires_at > created_at),
            CHECK(
                NOT (
                    consumed_at IS NOT NULL
                    AND revoked_at IS NOT NULL
                )
            )
        );

        CREATE INDEX idx_capability_confirmations_session
            ON capability_confirmations(session_id_hash);

        CREATE INDEX idx_capability_confirmations_user_business
            ON capability_confirmations(user_id, business_id);

        CREATE INDEX idx_capability_confirmations_expires
            ON capability_confirmations(expires_at);

        CREATE INDEX idx_capability_confirmations_pending
            ON capability_confirmations(
                business_id,
                session_id_hash,
                expires_at
            )
            WHERE consumed_at IS NULL
              AND revoked_at IS NULL;
        """
    )


def _migrate_v11_to_v12(connection: sqlite3.Connection) -> None:
    """Add explicit durable business capability entitlements."""
    connection.executescript(
        '''
        CREATE TABLE IF NOT EXISTS business_capability_entitlements (
            business_id TEXT PRIMARY KEY,
            configured_at TEXT NOT NULL,
            FOREIGN KEY(business_id)
                REFERENCES businesses(business_id)
                ON DELETE CASCADE,
            CHECK(length(business_id) > 0),
            CHECK(length(configured_at) > 0)
        );

        CREATE TABLE IF NOT EXISTS business_capability_grants (
            business_id TEXT NOT NULL,
            capability TEXT NOT NULL,
            PRIMARY KEY(business_id, capability),
            FOREIGN KEY(business_id)
                REFERENCES business_capability_entitlements(business_id)
                ON DELETE CASCADE,
            CHECK(length(business_id) > 0),
            CHECK(length(capability) > 0)
        );

        CREATE INDEX IF NOT EXISTS
        idx_business_capability_grants_capability
        ON business_capability_grants(capability);
        '''
    )




def _migrate_v12_to_v13(connection: sqlite3.Connection) -> None:
    """Add durable, user-scoped web conversation history."""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS web_conversation_turns (
            user_id TEXT NOT NULL,
            business_id TEXT NOT NULL,
            sequence INTEGER NOT NULL CHECK(sequence > 0),
            role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
            content TEXT NOT NULL CHECK(length(trim(content)) > 0),
            created_at TEXT NOT NULL CHECK(length(created_at) > 0),
            PRIMARY KEY(user_id, business_id, sequence),
            FOREIGN KEY(user_id)
                REFERENCES users(user_id) ON DELETE CASCADE,
            FOREIGN KEY(business_id)
                REFERENCES businesses(business_id) ON DELETE CASCADE
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_web_conversation_business_user
        ON web_conversation_turns(business_id, user_id, sequence)
        """
    )


def _migrate_v13_to_v14(connection: sqlite3.Connection) -> None:
    """Add durable, membership-scoped voice conversation history."""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS voice_conversations (
            conversation_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            business_id TEXT NOT NULL,
            created_at TEXT NOT NULL CHECK(length(trim(created_at)) > 0),
            updated_at TEXT NOT NULL CHECK(length(trim(updated_at)) > 0),
            FOREIGN KEY(user_id, business_id)
                REFERENCES business_memberships(user_id, business_id)
                ON DELETE CASCADE
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_voice_conversations_owner_updated
        ON voice_conversations(user_id, business_id, updated_at)
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS voice_conversation_turns (
            conversation_id TEXT NOT NULL,
            sequence INTEGER NOT NULL CHECK(sequence > 0),
            role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
            content TEXT NOT NULL CHECK(length(trim(content)) > 0),
            created_at TEXT NOT NULL CHECK(length(trim(created_at)) > 0),
            PRIMARY KEY(conversation_id, sequence),
            FOREIGN KEY(conversation_id)
                REFERENCES voice_conversations(conversation_id)
                ON DELETE CASCADE
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_voice_turns_conversation_sequence
        ON voice_conversation_turns(conversation_id, sequence)
        """
    )


def _migrate_v14_to_v15(connection: sqlite3.Connection) -> None:
    """Add tenant-scoped metadata for immutable Forge artifacts."""
    connection.execute(
        """
        CREATE TABLE forge_artifacts (
            artifact_id TEXT PRIMARY KEY,
            business_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            sha256 TEXT NOT NULL
                CHECK(
                    length(sha256) = 64
                    AND sha256 NOT GLOB '*[^0-9a-f]*'
                ),
            size_bytes INTEGER NOT NULL CHECK(size_bytes >= 0),
            media_type TEXT NOT NULL CHECK(length(trim(media_type)) > 0),
            storage_key TEXT NOT NULL CHECK(length(trim(storage_key)) > 0),
            created_at TEXT NOT NULL CHECK(length(trim(created_at)) > 0),
            FOREIGN KEY(business_id)
                REFERENCES businesses(business_id)
                ON DELETE CASCADE,
            UNIQUE(business_id, project_id, artifact_id)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX idx_forge_artifacts_project
        ON forge_artifacts(business_id, project_id, created_at)
        """
    )


def _migrate_v15_to_v16(connection: sqlite3.Connection) -> None:
    """Preserve Forge artifact records when a business is deleted."""
    connection.execute("DROP INDEX IF EXISTS idx_forge_artifacts_project")
    connection.execute(
        "ALTER TABLE forge_artifacts RENAME TO forge_artifacts_v15"
    )
    connection.execute(
        """
        CREATE TABLE forge_artifacts (
            artifact_id TEXT PRIMARY KEY,
            business_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            sha256 TEXT NOT NULL
                CHECK(
                    length(sha256) = 64
                    AND sha256 NOT GLOB '*[^0-9a-f]*'
                ),
            size_bytes INTEGER NOT NULL CHECK(size_bytes >= 0),
            media_type TEXT NOT NULL CHECK(length(trim(media_type)) > 0),
            storage_key TEXT NOT NULL CHECK(length(trim(storage_key)) > 0),
            created_at TEXT NOT NULL CHECK(length(trim(created_at)) > 0),
            FOREIGN KEY(business_id)
                REFERENCES businesses(business_id)
                ON DELETE RESTRICT,
            UNIQUE(business_id, project_id, artifact_id)
        )
        """
    )
    connection.execute(
        """
        INSERT INTO forge_artifacts (
            artifact_id, business_id, project_id, sha256,
            size_bytes, media_type, storage_key, created_at
        )
        SELECT
            artifact_id, business_id, project_id, sha256,
            size_bytes, media_type, storage_key, created_at
        FROM forge_artifacts_v15
        """
    )
    connection.execute("DROP TABLE forge_artifacts_v15")
    connection.execute(
        """
        CREATE INDEX idx_forge_artifacts_project
        ON forge_artifacts(business_id, project_id, created_at)
        """
    )


def _migrate_v16_to_v17(connection: sqlite3.Connection) -> None:
    """Create tenant-scoped Forge projects and bind artifacts to their owner."""
    from datetime import datetime, timezone

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS forge_projects (
            business_id TEXT NOT NULL,
            project_id TEXT NOT NULL
                CHECK(length(trim(project_id)) > 0 AND length(project_id) <= 128),
            name TEXT NOT NULL
                CHECK(length(trim(name)) > 0 AND length(name) <= 160),
            description TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'ACTIVE'
                CHECK(status IN ('ACTIVE', 'ARCHIVED')),
            created_at TEXT NOT NULL CHECK(length(trim(created_at)) > 0),
            updated_at TEXT NOT NULL CHECK(length(trim(updated_at)) > 0),
            legacy_imported INTEGER NOT NULL DEFAULT 0
                CHECK(legacy_imported IN (0, 1)),
            PRIMARY KEY(business_id, project_id),
            FOREIGN KEY(business_id)
                REFERENCES businesses(business_id)
                ON DELETE RESTRICT,
            CHECK(updated_at >= created_at)
        )
        """
    )

    legacy_rows = connection.execute(
        """
        SELECT business_id, project_id, created_at
        FROM forge_artifacts
        ORDER BY business_id, project_id
        """
    ).fetchall()

    project_times: dict[tuple[str, str], list[datetime]] = {}
    for row in legacy_rows:
        try:
            created_at = datetime.fromisoformat(row["created_at"])
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                "Cannot migrate Forge artifact with an invalid creation timestamp."
            ) from exc

        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise RuntimeError(
                "Cannot migrate Forge artifact with a timezone-naive timestamp."
            )

        key = (row["business_id"], row["project_id"])
        project_times.setdefault(key, []).append(
            created_at.astimezone(timezone.utc)
        )

    for (business_id, project_id), timestamps in project_times.items():
        first_seen = min(timestamps).isoformat()
        last_seen = max(timestamps).isoformat()

        connection.execute(
            """
            INSERT OR IGNORE INTO forge_projects (
                business_id, project_id, name, description, status,
                created_at, updated_at, legacy_imported
            )
            VALUES (?, ?, ?, ?, 'ACTIVE', ?, ?, 1)
            """,
            (
                business_id,
                project_id,
                f"Imported project {project_id}",
                "Imported from existing Forge artifact records. Original project "
                "description and creation history were not available.",
                first_seen,
                last_seen,
            ),
        )

    connection.execute("DROP INDEX IF EXISTS idx_forge_artifacts_project")
    connection.execute("ALTER TABLE forge_artifacts RENAME TO forge_artifacts_v16")

    connection.execute(
        """
        CREATE TABLE forge_artifacts (
            artifact_id TEXT PRIMARY KEY,
            business_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            sha256 TEXT NOT NULL
                CHECK(
                    length(sha256) = 64
                    AND sha256 NOT GLOB '*[^0-9a-f]*'
                ),
            size_bytes INTEGER NOT NULL CHECK(size_bytes >= 0),
            media_type TEXT NOT NULL CHECK(length(trim(media_type)) > 0),
            storage_key TEXT NOT NULL CHECK(length(trim(storage_key)) > 0),
            created_at TEXT NOT NULL CHECK(length(trim(created_at)) > 0),
            FOREIGN KEY(business_id)
                REFERENCES businesses(business_id)
                ON DELETE RESTRICT,
            FOREIGN KEY(business_id, project_id)
                REFERENCES forge_projects(business_id, project_id)
                ON DELETE RESTRICT,
            UNIQUE(business_id, project_id, artifact_id)
        )
        """
    )

    connection.execute(
        """
        INSERT INTO forge_artifacts (
            artifact_id, business_id, project_id, sha256,
            size_bytes, media_type, storage_key, created_at
        )
        SELECT
            artifact_id, business_id, project_id, sha256,
            size_bytes, media_type, storage_key, created_at
        FROM forge_artifacts_v16
        """
    )
    connection.execute("DROP TABLE forge_artifacts_v16")

    connection.execute(
        """
        CREATE INDEX idx_forge_artifacts_project
        ON forge_artifacts(business_id, project_id, created_at)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_forge_projects_business_status
        ON forge_projects(business_id, status, updated_at)
        """
    )

    violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise RuntimeError(
            "Forge project migration produced foreign-key violations."
        )

def _migrate_v17_to_v18(connection: sqlite3.Connection) -> None:
    """Create durable, tenant-scoped Forge job storage."""
    connection.execute(
        """
        CREATE TABLE forge_jobs (
            business_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            job_id TEXT NOT NULL
                CHECK(length(trim(job_id)) > 0 AND length(job_id) <= 128),
            job_type TEXT NOT NULL
                CHECK(length(trim(job_type)) > 0 AND length(job_type) <= 256),
            status TEXT NOT NULL
                CHECK(status IN (
                    'queued', 'running', 'completed_vaulted',
                    'completed_vaulted_locked', 'failed', 'cancelled'
                )),
            phase TEXT NOT NULL
                CHECK(length(trim(phase)) > 0 AND length(phase) <= 256),
            progress INTEGER NOT NULL CHECK(progress BETWEEN 0 AND 100),
            created_at TEXT NOT NULL CHECK(length(trim(created_at)) > 0),
            updated_at TEXT NOT NULL CHECK(length(trim(updated_at)) > 0),
            heartbeat_at TEXT,
            started_at TEXT,
            completed_at TEXT,
            cancellation_requested INTEGER NOT NULL DEFAULT 0
                CHECK(cancellation_requested IN (0, 1)),
            checkpoint_json TEXT
                CHECK(
                    checkpoint_json IS NULL OR
                    length(CAST(checkpoint_json AS BLOB)) <= 16384
                ),
            error_code TEXT
                CHECK(error_code IS NULL OR
                    (length(trim(error_code)) BETWEEN 1 AND 256)),
            error_message TEXT
                CHECK(error_message IS NULL OR
                    (length(trim(error_message)) BETWEEN 1 AND 256)),
            revision INTEGER NOT NULL DEFAULT 1 CHECK(revision >= 1),

            PRIMARY KEY(business_id, project_id, job_id),

            FOREIGN KEY(business_id)
                REFERENCES businesses(business_id) ON DELETE RESTRICT,
            FOREIGN KEY(business_id, project_id)
                REFERENCES forge_projects(business_id, project_id)
                ON DELETE RESTRICT,

            CHECK(updated_at >= created_at),
            CHECK(started_at IS NULL OR
                (started_at >= created_at AND started_at <= updated_at)),
            CHECK(heartbeat_at IS NULL OR
                (started_at IS NOT NULL AND
                 heartbeat_at >= started_at AND heartbeat_at <= updated_at)),
            CHECK(completed_at IS NULL OR
                (completed_at >= created_at AND completed_at <= updated_at)),
            CHECK(completed_at IS NULL OR started_at IS NULL OR
                completed_at >= started_at),
            CHECK(completed_at IS NULL OR heartbeat_at IS NULL OR
                completed_at >= heartbeat_at),

            CHECK(
                (status = 'queued' AND started_at IS NULL AND completed_at IS NULL)
                OR
                (status = 'running' AND started_at IS NOT NULL AND completed_at IS NULL)
                OR
                (status IN (
                    'completed_vaulted', 'completed_vaulted_locked'
                ) AND started_at IS NOT NULL AND completed_at IS NOT NULL
                  AND progress = 100)
                OR
                (status IN ('failed', 'cancelled') AND completed_at IS NOT NULL)
            ),

            CHECK(
                (status = 'failed' AND error_code IS NOT NULL)
                OR
                (status != 'failed' AND error_code IS NULL
                 AND error_message IS NULL)
            )
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX idx_forge_jobs_project_created
        ON forge_jobs(business_id, project_id, created_at)
        """
    )
    connection.execute(
        """
        CREATE INDEX idx_forge_jobs_queue
        ON forge_jobs(status, created_at)
        """
    )

    violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise RuntimeError(
            "Forge job migration produced foreign-key violations."
        )


def _migrate_v18_to_v19(connection: sqlite3.Connection) -> None:
    """Add worker leases and fencing generations to Forge jobs."""
    connection.execute("ALTER TABLE forge_jobs ADD COLUMN worker_id TEXT")
    connection.execute("ALTER TABLE forge_jobs ADD COLUMN lease_expires_at TEXT")
    connection.execute("""
        ALTER TABLE forge_jobs
        ADD COLUMN lease_generation INTEGER NOT NULL DEFAULT 0
        CHECK(lease_generation >= 0)
    """)
    connection.execute("""
        CREATE INDEX idx_forge_jobs_running_lease
        ON forge_jobs(status, lease_expires_at)
        WHERE status = 'running'
    """)


def _migrate_v19_to_v20(connection: sqlite3.Connection) -> None:
    """Store immutable, tenant-scoped approved Forge task specifications."""
    connection.execute("""
        CREATE TABLE forge_task_specs (
            business_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            job_id TEXT NOT NULL,
            spec_json TEXT NOT NULL
                CHECK(length(CAST(spec_json AS BLOB)) <= 32768),
            spec_sha256 TEXT NOT NULL
                CHECK(length(spec_sha256) = 64
                      AND spec_sha256 = lower(spec_sha256)),
            created_at TEXT NOT NULL,
            PRIMARY KEY (business_id, project_id, job_id),
            FOREIGN KEY (business_id, project_id, job_id)
                REFERENCES forge_jobs (business_id, project_id, job_id)
                ON DELETE RESTRICT
        )
    """)



def _migrate_v20_to_v21(connection: sqlite3.Connection) -> None:
    """Register immutable GitHub repository identities for Forge projects."""
    connection.execute(
        """
        CREATE TABLE forge_project_repositories (
            business_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            provider TEXT NOT NULL CHECK(provider = 'github'),
            repository_owner TEXT NOT NULL
                CHECK(length(trim(repository_owner)) BETWEEN 1 AND 39),
            repository_name TEXT NOT NULL
                CHECK(length(trim(repository_name)) BETWEEN 1 AND 100),
            default_branch TEXT NOT NULL
                CHECK(length(trim(default_branch)) BETWEEN 1 AND 255),
            created_at TEXT NOT NULL CHECK(length(trim(created_at)) > 0),
            updated_at TEXT NOT NULL CHECK(length(trim(updated_at)) > 0),
            PRIMARY KEY(business_id, project_id),
            FOREIGN KEY(business_id, project_id)
                REFERENCES forge_projects(business_id, project_id)
                ON DELETE RESTRICT,
            CHECK(updated_at >= created_at)
        )
        """
    )


MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {
    1: _migrate_v1_to_v2,
    2: _migrate_v2_to_v3,
    3: _migrate_v3_to_v4,
    4: _migrate_v4_to_v5,
    5: _migrate_v5_to_v6,
    6: _migrate_v6_to_v7,
    7: _migrate_v7_to_v8,
    8: _migrate_v8_to_v9,
    9: _migrate_v9_to_v10,
    10: _migrate_v10_to_v11,
    11: _migrate_v11_to_v12,
    12: _migrate_v12_to_v13,
    13: _migrate_v13_to_v14,
    14: _migrate_v14_to_v15,
    15: _migrate_v15_to_v16,
    16: _migrate_v16_to_v17,
    17: _migrate_v17_to_v18,
    18: _migrate_v18_to_v19,
    19: _migrate_v19_to_v20,
    20: _migrate_v20_to_v21,
}

# Backwards-compatible name for callers that imported SCHEMA.
SCHEMA = BASE_SCHEMA
