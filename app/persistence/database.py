from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Callable, Iterator

SCHEMA_VERSION = 33
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



def _migrate_v21_to_v22(connection: sqlite3.Connection) -> None:
    """Add append-only, tenant-scoped Forge Sentinel assessment records."""
    connection.execute(
        """
        CREATE TABLE forge_sentinel_assessments (
            assessment_id TEXT PRIMARY KEY,
            business_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            job_id TEXT NOT NULL,
            artifact_ref TEXT NOT NULL
                CHECK(length(trim(artifact_ref)) BETWEEN 1 AND 512),
            candidate_sha256 TEXT NOT NULL
                CHECK(length(candidate_sha256) = 64)
                CHECK(candidate_sha256 NOT GLOB '*[^0-9a-f]*'),
            status TEXT NOT NULL
                CHECK(status IN ('BLOCKED', 'READY_FOR_USER_ACCEPTANCE')),
            blocked_at_guard TEXT
                CHECK(blocked_at_guard IS NULL OR blocked_at_guard IN (
                    'sentinel-guard-1',
                    'sentinel-guard-2',
                    'sentinel-guard-3',
                    'sentinel-guard-4',
                    'sentinel-guard-5'
                )),
            created_at TEXT NOT NULL CHECK(length(trim(created_at)) > 0),
            UNIQUE(business_id, project_id, job_id, assessment_id),
            FOREIGN KEY(business_id, project_id, job_id)
                REFERENCES forge_jobs(business_id, project_id, job_id)
                ON DELETE RESTRICT,
            CHECK(
                (status = 'READY_FOR_USER_ACCEPTANCE' AND blocked_at_guard IS NULL)
                OR
                (status = 'BLOCKED' AND blocked_at_guard IS NOT NULL)
            )
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE forge_sentinel_guard_results (
            assessment_id TEXT NOT NULL,
            business_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            job_id TEXT NOT NULL,
            guard_id TEXT NOT NULL CHECK(guard_id IN (
                'sentinel-guard-1',
                'sentinel-guard-2',
                'sentinel-guard-3',
                'sentinel-guard-4',
                'sentinel-guard-5'
            )),
            implementation_id TEXT,
            artifact_ref TEXT NOT NULL
                CHECK(length(trim(artifact_ref)) BETWEEN 1 AND 512),
            candidate_sha256 TEXT NOT NULL
                CHECK(length(candidate_sha256) = 64)
                CHECK(candidate_sha256 NOT GLOB '*[^0-9a-f]*'),
            verdict TEXT NOT NULL
                CHECK(verdict IN ('PASS', 'FAIL', 'INCONCLUSIVE')),
            findings_json TEXT NOT NULL CHECK(json_valid(findings_json)),
            reviewed_at TEXT NOT NULL CHECK(length(trim(reviewed_at)) > 0),
            PRIMARY KEY(assessment_id, guard_id),
            FOREIGN KEY(business_id, project_id, job_id, assessment_id)
                REFERENCES forge_sentinel_assessments(
                    business_id, project_id, job_id, assessment_id
                )
                ON DELETE RESTRICT
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX idx_forge_sentinel_job_latest
        ON forge_sentinel_assessments(
            business_id, project_id, job_id, created_at
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX idx_forge_sentinel_candidate
        ON forge_sentinel_assessments(
            business_id, project_id, job_id, candidate_sha256
        )
        """
    )

    connection.execute(
        """
        CREATE TRIGGER forge_sentinel_assessments_no_update
        BEFORE UPDATE ON forge_sentinel_assessments
        BEGIN
            SELECT RAISE(ABORT, 'Sentinel assessments are immutable');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER forge_sentinel_assessments_no_delete
        BEFORE DELETE ON forge_sentinel_assessments
        BEGIN
            SELECT RAISE(ABORT, 'Sentinel assessments are immutable');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER forge_sentinel_results_no_update
        BEFORE UPDATE ON forge_sentinel_guard_results
        BEGIN
            SELECT RAISE(ABORT, 'Sentinel Guard results are immutable');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER forge_sentinel_results_no_delete
        BEFORE DELETE ON forge_sentinel_guard_results
        BEGIN
            SELECT RAISE(ABORT, 'Sentinel Guard results are immutable');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER forge_sentinel_results_validate_insert
        BEFORE INSERT ON forge_sentinel_guard_results
        BEGIN
            SELECT CASE
                WHEN NOT EXISTS (
                    SELECT 1
                    FROM forge_sentinel_assessments a
                    WHERE a.assessment_id = NEW.assessment_id
                      AND a.business_id = NEW.business_id
                      AND a.project_id = NEW.project_id
                      AND a.job_id = NEW.job_id
                      AND a.artifact_ref = NEW.artifact_ref
                      AND a.candidate_sha256 = NEW.candidate_sha256
                )
                THEN RAISE(ABORT, 'Sentinel result scope or digest mismatch')
            END;

            SELECT CASE
                WHEN NEW.guard_id != CASE (
                    SELECT COUNT(*)
                    FROM forge_sentinel_guard_results r
                    WHERE r.assessment_id = NEW.assessment_id
                )
                    WHEN 0 THEN 'sentinel-guard-1'
                    WHEN 1 THEN 'sentinel-guard-2'
                    WHEN 2 THEN 'sentinel-guard-3'
                    WHEN 3 THEN 'sentinel-guard-4'
                    WHEN 4 THEN 'sentinel-guard-5'
                    ELSE ''
                END
                THEN RAISE(ABORT, 'Sentinel Guard sequence violation')
            END;

            SELECT CASE
                WHEN EXISTS (
                    SELECT 1
                    FROM forge_sentinel_guard_results r
                    WHERE r.assessment_id = NEW.assessment_id
                      AND r.verdict != 'PASS'
                )
                THEN RAISE(ABORT, 'Cannot advance after a non-PASS Guard')
            END;

            SELECT CASE
                WHEN (
                    SELECT status
                    FROM forge_sentinel_assessments
                    WHERE assessment_id = NEW.assessment_id
                ) = 'READY_FOR_USER_ACCEPTANCE'
                AND NEW.verdict != 'PASS'
                THEN RAISE(ABORT, 'User acceptance eligibility requires PASS')
            END;

            SELECT CASE
                WHEN (
                    SELECT status
                    FROM forge_sentinel_assessments
                    WHERE assessment_id = NEW.assessment_id
                ) = 'BLOCKED'
                AND NEW.guard_id = (
                    SELECT blocked_at_guard
                    FROM forge_sentinel_assessments
                    WHERE assessment_id = NEW.assessment_id
                )
                AND NEW.verdict = 'PASS'
                THEN RAISE(ABORT, 'Blocked Guard cannot PASS')
            END;

            SELECT CASE
                WHEN (
                    SELECT status
                    FROM forge_sentinel_assessments
                    WHERE assessment_id = NEW.assessment_id
                ) = 'BLOCKED'
                AND NEW.guard_id != (
                    SELECT blocked_at_guard
                    FROM forge_sentinel_assessments
                    WHERE assessment_id = NEW.assessment_id
                )
                AND NEW.verdict != 'PASS'
                THEN RAISE(ABORT, 'Only the final Guard may block the sequence')
            END;
        END
        """
    )



def _migrate_v22_to_v23(connection: sqlite3.Connection) -> None:
    """Create immutable, founder-authorised Forge acceptance decisions."""
    connection.execute("""
        CREATE TABLE forge_user_acceptance_decisions (
            decision_id TEXT PRIMARY KEY,
            business_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            job_id TEXT NOT NULL,
            artifact_ref TEXT NOT NULL,
            candidate_sha256 TEXT NOT NULL
                CHECK(
                    length(candidate_sha256) = 64
                    AND candidate_sha256 = lower(candidate_sha256)
                    AND candidate_sha256 NOT GLOB '*[^0-9a-f]*'
                ),
            sentinel_assessment_id TEXT NOT NULL,
            actor_user_id TEXT NOT NULL,
            decision TEXT NOT NULL
                CHECK(decision IN ('accepted', 'changes_requested')),
            live_test_confirmed INTEGER NOT NULL
                CHECK(live_test_confirmed IN (0, 1)),
            limitations_disclosed INTEGER NOT NULL
                CHECK(limitations_disclosed IN (0, 1)),
            feedback TEXT NOT NULL DEFAULT ''
                CHECK(length(CAST(feedback AS BLOB)) <= 4096),
            created_at TEXT NOT NULL,

            FOREIGN KEY(business_id, project_id, job_id)
                REFERENCES forge_jobs(business_id, project_id, job_id)
                ON DELETE RESTRICT,
            FOREIGN KEY(sentinel_assessment_id)
                REFERENCES forge_sentinel_assessments(assessment_id)
                ON DELETE RESTRICT,
            FOREIGN KEY(actor_user_id)
                REFERENCES platform_founders(user_id)
                ON DELETE RESTRICT,

            CHECK(
                decision != 'accepted'
                OR (live_test_confirmed = 1 AND limitations_disclosed = 1)
            ),
            CHECK(
                decision != 'changes_requested'
                OR length(trim(feedback)) > 0
            )
        )
    """)

    connection.execute("""
        CREATE INDEX idx_forge_acceptance_job
        ON forge_user_acceptance_decisions(
            business_id, project_id, job_id, created_at
        )
    """)

    connection.execute("""
        CREATE INDEX idx_forge_acceptance_artifact
        ON forge_user_acceptance_decisions(
            business_id, project_id, job_id, artifact_ref, candidate_sha256
        )
    """)

    connection.execute("""
        CREATE TRIGGER forge_acceptance_no_update
        BEFORE UPDATE ON forge_user_acceptance_decisions
        BEGIN
            SELECT RAISE(ABORT, 'Forge acceptance decisions are immutable');
        END
    """)

    connection.execute("""
        CREATE TRIGGER forge_acceptance_no_delete
        BEFORE DELETE ON forge_user_acceptance_decisions
        BEGIN
            SELECT RAISE(ABORT, 'Forge acceptance decisions are immutable');
        END
    """)

    connection.execute("""
        CREATE TRIGGER forge_acceptance_validate_insert
        BEFORE INSERT ON forge_user_acceptance_decisions
        BEGIN
            SELECT CASE
                WHEN NOT EXISTS (
                    SELECT 1 FROM platform_founders f
                    WHERE f.user_id = NEW.actor_user_id AND f.active = 1
                )
                THEN RAISE(ABORT, 'Active founder authority required')
            END;

            SELECT CASE
                WHEN NOT EXISTS (
                    SELECT 1 FROM forge_jobs j
                    WHERE j.business_id = NEW.business_id
                      AND j.project_id = NEW.project_id
                      AND j.job_id = NEW.job_id
                      AND j.status = 'completed_vaulted'
                )
                THEN RAISE(ABORT, 'Completed unlocked Forge job required')
            END;

            SELECT CASE
                WHEN NOT EXISTS (
                    SELECT 1 FROM forge_sentinel_assessments a
                    WHERE a.assessment_id = NEW.sentinel_assessment_id
                      AND a.business_id = NEW.business_id
                      AND a.project_id = NEW.project_id
                      AND a.job_id = NEW.job_id
                      AND a.artifact_ref = NEW.artifact_ref
                      AND a.candidate_sha256 = NEW.candidate_sha256
                      AND a.status = 'READY_FOR_USER_ACCEPTANCE'
                )
                THEN RAISE(ABORT, 'Matching Sentinel assessment required')
            END;

            SELECT CASE
                WHEN (
                    SELECT COUNT(*)
                    FROM forge_sentinel_guard_results r
                    WHERE r.assessment_id = NEW.sentinel_assessment_id
                      AND r.verdict = 'PASS'
                      AND r.artifact_ref = NEW.artifact_ref
                      AND r.candidate_sha256 = NEW.candidate_sha256
                ) != 5
                THEN RAISE(ABORT, 'All five Sentinel Guards must PASS')
            END;
        END
    """)



def _migrate_v23_to_v24(connection: sqlite3.Connection) -> None:
    """Create tenant-scoped integration connections, permissions and secrets."""
    connection.executescript("""
        CREATE TABLE integration_connections (
            connection_id TEXT PRIMARY KEY,
            business_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            external_account_id TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('active', 'revoked')),
            created_at TEXT NOT NULL,
            revoked_at TEXT,
            UNIQUE(connection_id, business_id, user_id)
        );

        CREATE INDEX idx_integration_connections_owner
        ON integration_connections(business_id, user_id, provider, status);

        CREATE TABLE integration_permissions (
            permission_id TEXT PRIMARY KEY,
            connection_id TEXT NOT NULL,
            business_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            scope TEXT NOT NULL,
            granted_at TEXT NOT NULL,
            revoked_at TEXT,
            FOREIGN KEY(connection_id, business_id, user_id)
                REFERENCES integration_connections(
                    connection_id, business_id, user_id
                ) ON DELETE RESTRICT,
            UNIQUE(connection_id, scope)
        );

        CREATE INDEX idx_integration_permissions_lookup
        ON integration_permissions(
            business_id, user_id, connection_id, scope, revoked_at
        );

        CREATE TABLE integration_secrets (
            connection_id TEXT PRIMARY KEY,
            business_id TEXT NOT NULL,
            encrypted_payload BLOB NOT NULL,
            key_version TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(connection_id, business_id)
                REFERENCES integration_connections(connection_id, business_id)
                ON DELETE RESTRICT
        );

        CREATE TABLE integration_audit_events (
            event_id TEXT PRIMARY KEY,
            business_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            connection_id TEXT,
            event_type TEXT NOT NULL,
            scope TEXT,
            created_at TEXT NOT NULL,
            details_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE INDEX idx_integration_audit_tenant
        ON integration_audit_events(business_id, created_at);

        CREATE TRIGGER integration_audit_no_update
        BEFORE UPDATE ON integration_audit_events
        BEGIN
            SELECT RAISE(ABORT, 'Integration audit events are immutable');
        END;

        CREATE TRIGGER integration_audit_no_delete
        BEFORE DELETE ON integration_audit_events
        BEGIN
            SELECT RAISE(ABORT, 'Integration audit events are immutable');
        END;
    """)



def _migrate_v24_to_v25(connection: sqlite3.Connection) -> None:
    """Add the exact unique parent key required by integration secret foreign keys."""
    connection.execute("""
        CREATE UNIQUE INDEX idx_integration_connections_secret_fk
        ON integration_connections(connection_id, business_id)
    """)



def _migrate_v25_to_v26(connection: sqlite3.Connection) -> None:
    """Store short-lived, single-use OAuth authorisation attempts."""
    connection.execute("""
        CREATE TABLE oauth_authorization_attempts (
            state_hash TEXT PRIMARY KEY,
            business_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            redirect_uri TEXT NOT NULL,
            encrypted_code_verifier BLOB NOT NULL,
            key_version TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            consumed_at TEXT
        )
    """)
    connection.execute("""
        CREATE INDEX idx_oauth_attempts_owner
        ON oauth_authorization_attempts(
            business_id, user_id, provider, expires_at
        )
    """)



def _migrate_v26_to_v27(connection: sqlite3.Connection) -> None:
    connection.execute("""
        CREATE TABLE owner_lifestyle_preferences (
            business_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            timezone TEXT NOT NULL DEFAULT 'UTC',
            wake_time TEXT,
            sleep_time TEXT,
            work_start TEXT,
            work_end TEXT,
            quiet_start TEXT,
            quiet_end TEXT,
            briefing_enabled INTEGER NOT NULL DEFAULT 1,
            briefing_time TEXT NOT NULL DEFAULT '07:00',
            initiative_level TEXT NOT NULL DEFAULT 'balanced',
            personality TEXT NOT NULL DEFAULT 'natural',
            preferred_channels TEXT NOT NULL DEFAULT '["whatsapp"]',
            critical_alerts_during_quiet INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (business_id, user_id),
            FOREIGN KEY (business_id) REFERENCES businesses(business_id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
        )
    """)
    connection.execute("""
        CREATE TABLE owner_routine_suggestions (
            suggestion_id TEXT PRIMARY KEY,
            business_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            field_name TEXT NOT NULL,
            proposed_value TEXT NOT NULL,
            observation_count INTEGER NOT NULL DEFAULT 1,
            first_observed_at TEXT NOT NULL,
            last_observed_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending', 'accepted', 'rejected')),
            resolved_at TEXT,
            UNIQUE(business_id, user_id, field_name, proposed_value),
            FOREIGN KEY(business_id, user_id)
                REFERENCES owner_lifestyle_preferences(business_id, user_id)
                ON DELETE CASCADE
        )
    """)
    connection.execute("""
        CREATE INDEX idx_owner_routine_pending
        ON owner_routine_suggestions(business_id, user_id, status)
    """)



def _migrate_v27_to_v28(connection: sqlite3.Connection) -> None:
    connection.execute("""
        CREATE TABLE attention_events (
            event_id TEXT PRIMARY KEY,
            business_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            event_type TEXT NOT NULL,
            severity TEXT NOT NULL
                CHECK(severity IN ('critical', 'important', 'routine')),
            title TEXT NOT NULL,
            details TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL DEFAULT '{}',
            action TEXT NOT NULL
                CHECK(action IN ('interrupt', 'deliver', 'defer', 'briefing', 'queue')),
            reason TEXT NOT NULL,
            evaluated_at TEXT NOT NULL,
            local_time TEXT NOT NULL,
            quiet_hours_active INTEGER NOT NULL DEFAULT 0,
            deliver_after TEXT,
            status TEXT NOT NULL
                CHECK(status IN (
                    'queued', 'deferred', 'briefing',
                    'delivered', 'acknowledged', 'failed'
                )),
            attempts INTEGER NOT NULL DEFAULT 0,
            provider_message_id TEXT,
            last_attempt_at TEXT,
            delivered_at TEXT,
            acknowledged_at TEXT,
            failure_reason TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(business_id, user_id, idempotency_key),
            FOREIGN KEY(business_id, user_id)
                REFERENCES owner_lifestyle_preferences(business_id, user_id)
                ON DELETE CASCADE
        )
    """)
    connection.execute("""
        CREATE INDEX idx_attention_events_pending
        ON attention_events(business_id, user_id, status, created_at)
    """)
    connection.execute("""
        CREATE INDEX idx_attention_events_due
        ON attention_events(status, deliver_after)
    """)




def _migrate_v28_to_v29(connection: sqlite3.Connection) -> None:
    """Add durable worker leases and retry scheduling to attention events."""
    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(attention_events)")
    }
    additions = {
        "claim_token": "TEXT",
        "claimed_by": "TEXT",
        "claimed_at": "TEXT",
        "lease_expires_at": "TEXT",
        "retry_after": "TEXT",
    }
    for name, sql_type in additions.items():
        if name not in columns:
            connection.execute(
                f"ALTER TABLE attention_events ADD COLUMN {name} {sql_type}"
            )

    connection.execute("""
        CREATE INDEX IF NOT EXISTS idx_attention_events_claimable
        ON attention_events(status, deliver_after, retry_after, lease_expires_at)
    """)



def _migrate_v29_to_v30(connection: sqlite3.Connection) -> None:
    """Create tenant-scoped multi-channel owner communication storage."""
    connection.execute("""
        CREATE TABLE owner_communication_channels (
            endpoint_id TEXT PRIMARY KEY,
            business_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            channel TEXT NOT NULL CHECK(
                channel IN ('whatsapp', 'sms', 'email', 'voice', 'companion_app')
            ),
            encrypted_endpoint BLOB NOT NULL,
            key_version TEXT NOT NULL,
            endpoint_fingerprint TEXT NOT NULL,
            verified_at TEXT,
            consent_granted_at TEXT,
            revoked_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(business_id, user_id, channel, endpoint_fingerprint),
            FOREIGN KEY(business_id, user_id)
                REFERENCES owner_lifestyle_preferences(business_id, user_id)
                ON DELETE CASCADE
        )
    """)
    connection.execute("""
        CREATE INDEX idx_owner_channels_enabled
        ON owner_communication_channels(
            business_id, user_id, channel, revoked_at, verified_at
        )
    """)
    connection.execute("""
        CREATE TABLE tenant_communication_identities (
            business_id TEXT PRIMARY KEY,
            provider TEXT NOT NULL,
            encrypted_identity BLOB NOT NULL,
            key_version TEXT NOT NULL,
            status TEXT NOT NULL CHECK(
                status IN ('pending', 'active', 'suspended', 'released')
            ),
            provisioned_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    connection.execute("""
        CREATE TABLE attention_delivery_attempts (
            delivery_id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL,
            business_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            endpoint_id TEXT NOT NULL,
            channel TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN (
                'queued', 'claimed', 'sent', 'delivered',
                'acknowledged', 'failed', 'unknown', 'cancelled'
            )),
            attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0),
            max_attempts INTEGER NOT NULL DEFAULT 3 CHECK(max_attempts > 0),
            next_attempt_at TEXT,
            claim_token TEXT,
            lease_expires_at TEXT,
            provider_reference TEXT,
            last_attempt_at TEXT,
            delivered_at TEXT,
            acknowledged_at TEXT,
            failure_reason TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(event_id, endpoint_id),
            FOREIGN KEY(event_id) REFERENCES attention_events(event_id)
                ON DELETE CASCADE,
            FOREIGN KEY(endpoint_id) REFERENCES owner_communication_channels(endpoint_id)
                ON DELETE RESTRICT
        )
    """)
    connection.execute("""
        CREATE INDEX idx_attention_delivery_due
        ON attention_delivery_attempts(status, next_attempt_at, lease_expires_at)
    """)
    connection.execute("""
        CREATE INDEX idx_attention_delivery_tenant
        ON attention_delivery_attempts(business_id, user_id, event_id)
    """)

def _migrate_v30_to_v31(connection: sqlite3.Connection) -> None:
    connection.execute(
        "ALTER TABLE attention_delivery_attempts ADD COLUMN claimed_by TEXT"
    )


def _migrate_v31_to_v32(connection: sqlite3.Connection) -> None:
    """Create durable subscription, mandate, manual-payment and billing ledgers."""

    connection.execute("""
        CREATE TABLE subscription_plans (
            plan_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            amount TEXT NOT NULL CHECK(CAST(amount AS REAL) > 0),
            currency TEXT NOT NULL
                CHECK(length(currency) = 3 AND currency = upper(currency)),
            interval_months INTEGER NOT NULL CHECK(interval_months > 0),
            active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    connection.execute("""
        CREATE TABLE business_subscriptions (
            subscription_id TEXT PRIMARY KEY,
            business_id TEXT NOT NULL,
            plan_id TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN (
                'pending', 'active', 'past_due', 'cancelled', 'expired'
            )),
            current_period_start TEXT,
            current_period_end TEXT,
            cancel_at_period_end INTEGER NOT NULL DEFAULT 0
                CHECK(cancel_at_period_end IN (0, 1)),
            cancelled_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            CHECK(
                (current_period_start IS NULL AND current_period_end IS NULL)
                OR
                (current_period_start IS NOT NULL
                 AND current_period_end IS NOT NULL
                 AND current_period_end > current_period_start)
            ),
            FOREIGN KEY(business_id) REFERENCES businesses(business_id)
                ON DELETE RESTRICT,
            FOREIGN KEY(plan_id) REFERENCES subscription_plans(plan_id)
                ON DELETE RESTRICT
        )
    """)

    connection.execute("""
        CREATE UNIQUE INDEX idx_one_open_subscription_per_business
        ON business_subscriptions(business_id)
        WHERE status IN ('pending', 'active', 'past_due')
    """)

    connection.execute("""
        CREATE INDEX idx_subscription_due_period
        ON business_subscriptions(status, current_period_end)
    """)

    connection.execute("""
        CREATE TABLE recurring_payment_mandates (
            mandate_id TEXT PRIMARY KEY,
            subscription_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            provider_mandate_id TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN (
                'pending', 'active', 'revoked', 'failed'
            )),
            approved_by_user_id TEXT NOT NULL,
            approved_at TEXT NOT NULL,
            consent_version TEXT NOT NULL,
            authorised_at TEXT,
            revoked_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(provider, provider_mandate_id),
            FOREIGN KEY(subscription_id)
                REFERENCES business_subscriptions(subscription_id)
                ON DELETE RESTRICT,
            FOREIGN KEY(approved_by_user_id) REFERENCES users(user_id)
                ON DELETE RESTRICT
        )
    """)

    connection.execute("""
        CREATE INDEX idx_recurring_mandates_subscription
        ON recurring_payment_mandates(subscription_id, status)
    """)

    connection.execute("""
        CREATE TABLE manual_payment_requests (
            request_id TEXT PRIMARY KEY,
            business_id TEXT NOT NULL,
            subscription_id TEXT NOT NULL,
            submitted_by_user_id TEXT NOT NULL,
            amount TEXT NOT NULL CHECK(CAST(amount AS REAL) > 0),
            currency TEXT NOT NULL
                CHECK(length(currency) = 3 AND currency = upper(currency)),
            payment_reference TEXT NOT NULL,
            evidence_reference TEXT,
            status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN (
                'pending', 'verified', 'rejected', 'cancelled'
            )),
            reviewed_by_user_id TEXT,
            review_reason TEXT,
            submitted_at TEXT NOT NULL,
            reviewed_at TEXT,
            FOREIGN KEY(business_id) REFERENCES businesses(business_id)
                ON DELETE RESTRICT,
            FOREIGN KEY(subscription_id)
                REFERENCES business_subscriptions(subscription_id)
                ON DELETE RESTRICT,
            FOREIGN KEY(submitted_by_user_id) REFERENCES users(user_id)
                ON DELETE RESTRICT,
            FOREIGN KEY(reviewed_by_user_id) REFERENCES users(user_id)
                ON DELETE RESTRICT
        )
    """)

    connection.execute("""
        CREATE INDEX idx_manual_payment_review_queue
        ON manual_payment_requests(status, submitted_at)
    """)

    connection.execute("""
        CREATE TABLE subscription_billing_periods (
            billing_period_id TEXT PRIMARY KEY,
            subscription_id TEXT NOT NULL,
            business_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            provider_event_id TEXT NOT NULL,
            period_start TEXT NOT NULL,
            period_end TEXT NOT NULL,
            amount TEXT NOT NULL CHECK(CAST(amount AS REAL) > 0),
            currency TEXT NOT NULL
                CHECK(length(currency) = 3 AND currency = upper(currency)),
            paid_at TEXT NOT NULL,
            recorded_at TEXT NOT NULL,
            CHECK(period_end > period_start),
            UNIQUE(provider, provider_event_id),
            UNIQUE(subscription_id, period_start),
            FOREIGN KEY(subscription_id)
                REFERENCES business_subscriptions(subscription_id)
                ON DELETE RESTRICT,
            FOREIGN KEY(business_id) REFERENCES businesses(business_id)
                ON DELETE RESTRICT,
            FOREIGN KEY(provider, provider_event_id)
                REFERENCES purchase_records(provider, provider_event_id)
                ON DELETE RESTRICT
        )
    """)

    connection.execute("""
        CREATE INDEX idx_billing_period_business
        ON subscription_billing_periods(business_id, period_end)
    """)



def _migrate_v32_to_v33(conn: sqlite3.Connection) -> None:
    """Create durable records for provider checkout attempts."""
    conn.execute("""
        CREATE TABLE payment_attempts (
            attempt_id TEXT PRIMARY KEY,
            business_id TEXT NOT NULL,
            subscription_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            amount TEXT NOT NULL,
            currency TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'created'
                CHECK (status IN (
                    'created', 'checkout_created', 'pending',
                    'failed', 'expired', 'cancelled', 'settled'
                )),
            provider_checkout_id TEXT,
            provider_payment_id TEXT,
            checkout_url TEXT,
            failure_reason TEXT,
            expires_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (business_id, idempotency_key),
            UNIQUE (provider, provider_checkout_id),
            UNIQUE (provider, provider_payment_id)
        )
    """)
    conn.execute("""
        CREATE INDEX idx_payment_attempts_business_status
        ON payment_attempts (business_id, status, created_at)
    """)
    conn.execute("""
        CREATE INDEX idx_payment_attempts_subscription_status
        ON payment_attempts (subscription_id, business_id, status)
    """)


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
    21: _migrate_v21_to_v22,
    22: _migrate_v22_to_v23,
    23: _migrate_v23_to_v24,
    24: _migrate_v24_to_v25,
    25: _migrate_v25_to_v26,
    26: _migrate_v26_to_v27,
    27: _migrate_v27_to_v28,
    28: _migrate_v28_to_v29,
    29: _migrate_v29_to_v30,
    30: _migrate_v30_to_v31,
    31: _migrate_v31_to_v32,
    32: _migrate_v32_to_v33,
}

# Backwards-compatible name for callers that imported SCHEMA.
SCHEMA = BASE_SCHEMA
