#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(pwd)"
if [[ ! -f "$PROJECT_ROOT/requirements.txt" || ! -d "$PROJECT_ROOT/app" || ! -d "$PROJECT_ROOT/tests" ]]; then
  echo "ERROR: run this script from ~/ai-business-assistant" >&2
  exit 1
fi

if [[ ! -f "$PROJECT_ROOT/app/identity/models.py" ]]; then
  echo "ERROR: current identity boundary is missing. Restore the existing Step 1 identity work before installing Step 0 persistence." >&2
  exit 1
fi

mkdir -p app/persistence

cat > app/persistence/__init__.py <<'PY'
"""Durable persistence infrastructure and repository implementations."""

from app.persistence.database import SQLiteDatabase

__all__ = ["SQLiteDatabase"]
PY

cat > app/persistence/database.py <<'PY'
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
PY

cat > app/persistence/serialization.py <<'PY'
from __future__ import annotations

from datetime import datetime, timezone


def datetime_to_storage(value: datetime) -> str:
    if not isinstance(value, datetime):
        raise TypeError("value must be a datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("value must be timezone-aware.")
    return value.astimezone(timezone.utc).isoformat()


def datetime_from_storage(value: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("stored datetime must be a non-empty string.")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("stored datetime must be timezone-aware.")
    return parsed
PY

cat > app/persistence/business_repository.py <<'PY'
from __future__ import annotations

from app.models.business import Business
from app.persistence.database import SQLiteDatabase


class SQLiteBusinessRepository:
    """Durable repository for business configuration."""

    def __init__(self, database: SQLiteDatabase) -> None:
        if not isinstance(database, SQLiteDatabase):
            raise TypeError("database must be a SQLiteDatabase.")
        self._database = database

    def save(self, business: Business) -> Business:
        if not isinstance(business, Business):
            raise TypeError("business must be a Business.")
        with self._database.connection() as connection:
            connection.execute(
                """INSERT INTO businesses
                   (business_id, name, owner_name, assistant_name, assistant_voice)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(business_id) DO UPDATE SET
                     name=excluded.name, owner_name=excluded.owner_name,
                     assistant_name=excluded.assistant_name, assistant_voice=excluded.assistant_voice""",
                (business.business_id, business.name, business.owner_name,
                 business.assistant_name, business.assistant_voice),
            )
        return business

    def get(self, business_id: str) -> Business | None:
        _validate_id(business_id)
        with self._database.connection() as connection:
            row = connection.execute(
                "SELECT business_id, name, owner_name, assistant_name, assistant_voice FROM businesses WHERE business_id = ?",
                (business_id,),
            ).fetchone()
        return Business(**dict(row)) if row else None


def _validate_id(value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("identifier must be a non-empty string.")
    if len(value) > 128:
        raise ValueError("identifier exceeds the maximum allowed length.")
PY

cat > app/persistence/user_repository.py <<'PY'
from __future__ import annotations

from app.identity.models import User
from app.persistence.database import SQLiteDatabase


class SQLiteUserRepository:
    """Durable identity repository; authentication secrets are separate."""

    def __init__(self, database: SQLiteDatabase) -> None:
        if not isinstance(database, SQLiteDatabase):
            raise TypeError("database must be a SQLiteDatabase.")
        self._database = database

    def save(self, user: User) -> User:
        if not isinstance(user, User):
            raise TypeError("user must be a User.")
        with self._database.connection() as connection:
            connection.execute(
                """INSERT INTO users(user_id, display_name, email) VALUES (?, ?, ?)
                   ON CONFLICT(user_id) DO UPDATE SET
                     display_name=excluded.display_name, email=excluded.email""",
                (user.user_id, user.display_name, user.email),
            )
        return user

    def get(self, user_id: str) -> User | None:
        _validate_id(user_id)
        with self._database.connection() as connection:
            row = connection.execute(
                "SELECT user_id, display_name, email FROM users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return User(**dict(row)) if row else None

    def get_by_email(self, email: str) -> User | None:
        if not isinstance(email, str) or not email.strip():
            raise ValueError("email must be a non-empty string.")
        with self._database.connection() as connection:
            row = connection.execute(
                "SELECT user_id, display_name, email FROM users WHERE email = ? COLLATE NOCASE",
                (email,),
            ).fetchone()
        return User(**dict(row)) if row else None


def _validate_id(value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("identifier must be a non-empty string.")
    if len(value) > 128:
        raise ValueError("identifier exceeds the maximum allowed length.")
PY

cat > app/persistence/membership_repository.py <<'PY'
from __future__ import annotations

from app.identity.models import BusinessMembership, UserRole
from app.persistence.database import SQLiteDatabase


class SQLiteMembershipRepository:
    """Durable user-to-business authorization membership repository."""

    def __init__(self, database: SQLiteDatabase) -> None:
        if not isinstance(database, SQLiteDatabase):
            raise TypeError("database must be a SQLiteDatabase.")
        self._database = database

    def save(self, membership: BusinessMembership) -> BusinessMembership:
        if not isinstance(membership, BusinessMembership):
            raise TypeError("membership must be a BusinessMembership.")
        with self._database.connection() as connection:
            connection.execute(
                """INSERT INTO business_memberships(user_id, business_id, role)
                   VALUES (?, ?, ?)
                   ON CONFLICT(user_id, business_id) DO UPDATE SET role=excluded.role""",
                (membership.user_id, membership.business_id, membership.role.value),
            )
        return membership

    def get(self, user_id: str, business_id: str) -> BusinessMembership | None:
        _validate_id(user_id)
        _validate_id(business_id)
        with self._database.connection() as connection:
            row = connection.execute(
                "SELECT user_id, business_id, role FROM business_memberships WHERE user_id = ? AND business_id = ?",
                (user_id, business_id),
            ).fetchone()
        if row is None:
            return None
        return BusinessMembership(row["user_id"], row["business_id"], UserRole(row["role"]))

    def list_for_business(self, business_id: str) -> list[BusinessMembership]:
        _validate_id(business_id)
        with self._database.connection() as connection:
            rows = connection.execute(
                "SELECT user_id, business_id, role FROM business_memberships WHERE business_id = ? ORDER BY user_id",
                (business_id,),
            ).fetchall()
        return [BusinessMembership(r["user_id"], r["business_id"], UserRole(r["role"])) for r in rows]


def _validate_id(value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("identifier must be a non-empty string.")
    if len(value) > 128:
        raise ValueError("identifier exceeds the maximum allowed length.")
PY

cat > app/persistence/memory_repository.py <<'PY'
from __future__ import annotations

import sqlite3

from app.models.memory import Memory
from app.persistence.database import SQLiteDatabase


class SQLiteMemoryRepository:
    """Durable implementation of the existing MemoryRepository contract."""

    MAX_ID_LENGTH = 128

    def __init__(self, database: SQLiteDatabase) -> None:
        if not isinstance(database, SQLiteDatabase):
            raise TypeError("database must be a SQLiteDatabase.")
        self._database = database

    def save(self, memory: Memory) -> Memory:
        if not isinstance(memory, Memory):
            raise TypeError("memory must be a Memory.")
        self._validate_id(memory.memory_id)
        self._validate_id(memory.business_id)
        with self._database.connection() as connection:
            try:
                connection.execute(
                    """INSERT INTO memories(memory_id, business_id, content, memory_type, importance)
                       VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(memory_id) DO UPDATE SET
                         business_id=excluded.business_id, content=excluded.content,
                         memory_type=excluded.memory_type, importance=excluded.importance""",
                    (memory.memory_id, memory.business_id, memory.content, memory.memory_type, memory.importance),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("business_id does not reference an existing business.") from exc
        return memory

    def get(self, memory_id: str) -> Memory | None:
        self._validate_id(memory_id)
        with self._database.connection() as connection:
            row = connection.execute(
                "SELECT memory_id, business_id, content, memory_type, importance FROM memories WHERE memory_id = ?",
                (memory_id,),
            ).fetchone()
        return Memory(**dict(row)) if row else None

    def list_for_business(self, business_id: str) -> list[Memory]:
        self._validate_id(business_id)
        with self._database.connection() as connection:
            rows = connection.execute(
                "SELECT memory_id, business_id, content, memory_type, importance FROM memories WHERE business_id = ? ORDER BY memory_id",
                (business_id,),
            ).fetchall()
        return [Memory(**dict(row)) for row in rows]

    def delete(self, memory_id: str) -> bool:
        self._validate_id(memory_id)
        with self._database.connection() as connection:
            cursor = connection.execute("DELETE FROM memories WHERE memory_id = ?", (memory_id,))
        return cursor.rowcount == 1

    @classmethod
    def _validate_id(cls, value: object) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("identifier must be a non-empty string.")
        if len(value) > cls.MAX_ID_LENGTH:
            raise ValueError("identifier exceeds the maximum allowed length.")
PY

cat > app/persistence/session.py <<'PY'
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.identity.models import UserRole
from app.persistence.database import SQLiteDatabase
from app.persistence.serialization import datetime_from_storage, datetime_to_storage


@dataclass(frozen=True)
class SessionRecord:
    """Server-side opaque session state; only a session hash is stored."""

    session_id_hash: str
    user_id: str
    business_id: str
    role: UserRole
    created_at: datetime
    expires_at: datetime
    last_seen_at: datetime
    revoked_at: datetime | None = None

    def __post_init__(self) -> None:
        for name, value in {
            "session_id_hash": self.session_id_hash,
            "user_id": self.user_id,
            "business_id": self.business_id,
        }.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string.")
        if not isinstance(self.role, UserRole):
            raise TypeError("role must be a UserRole.")
        for name, value in {
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "last_seen_at": self.last_seen_at,
        }.items():
            if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware.")
        if self.revoked_at is not None and (self.revoked_at.tzinfo is None or self.revoked_at.utcoffset() is None):
            raise ValueError("revoked_at must be timezone-aware when present.")
        if len(self.session_id_hash) > 256:
            raise ValueError("session_id_hash is too long.")


class SQLiteSessionRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        if not isinstance(database, SQLiteDatabase):
            raise TypeError("database must be a SQLiteDatabase.")
        self._database = database

    def save(self, session: SessionRecord) -> SessionRecord:
        if not isinstance(session, SessionRecord):
            raise TypeError("session must be a SessionRecord.")
        with self._database.connection() as connection:
            connection.execute(
                """INSERT INTO sessions(session_id_hash, user_id, business_id, role, created_at, expires_at, last_seen_at, revoked_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(session_id_hash) DO UPDATE SET
                     user_id=excluded.user_id, business_id=excluded.business_id, role=excluded.role,
                     created_at=excluded.created_at, expires_at=excluded.expires_at,
                     last_seen_at=excluded.last_seen_at, revoked_at=excluded.revoked_at""",
                (session.session_id_hash, session.user_id, session.business_id, session.role.value,
                 datetime_to_storage(session.created_at), datetime_to_storage(session.expires_at),
                 datetime_to_storage(session.last_seen_at),
                 datetime_to_storage(session.revoked_at) if session.revoked_at else None),
            )
        return session

    def get(self, session_id_hash: str) -> SessionRecord | None:
        if not isinstance(session_id_hash, str) or not session_id_hash.strip():
            raise ValueError("session_id_hash must be a non-empty string.")
        with self._database.connection() as connection:
            row = connection.execute("SELECT * FROM sessions WHERE session_id_hash = ?", (session_id_hash,)).fetchone()
        return _from_row(row) if row else None

    def revoke(self, session_id_hash: str, revoked_at: datetime) -> bool:
        if not isinstance(session_id_hash, str) or not session_id_hash.strip():
            raise ValueError("session_id_hash must be a non-empty string.")
        if not isinstance(revoked_at, datetime) or revoked_at.tzinfo is None or revoked_at.utcoffset() is None:
            raise ValueError("revoked_at must be timezone-aware.")
        with self._database.connection() as connection:
            cursor = connection.execute(
                "UPDATE sessions SET revoked_at = ? WHERE session_id_hash = ? AND revoked_at IS NULL",
                (datetime_to_storage(revoked_at), session_id_hash),
            )
        return cursor.rowcount == 1


def _from_row(row) -> SessionRecord:
    return SessionRecord(
        session_id_hash=row["session_id_hash"], user_id=row["user_id"], business_id=row["business_id"],
        role=UserRole(row["role"]), created_at=datetime_from_storage(row["created_at"]),
        expires_at=datetime_from_storage(row["expires_at"]), last_seen_at=datetime_from_storage(row["last_seen_at"]),
        revoked_at=datetime_from_storage(row["revoked_at"]) if row["revoked_at"] else None,
    )
PY

cat > app/persistence/trial_repository.py <<'PY'
from __future__ import annotations

from datetime import datetime

from app.commercial.trial import BusinessTrial
from app.persistence.database import SQLiteDatabase
from app.persistence.serialization import datetime_from_storage, datetime_to_storage


class SQLiteTrialRepository:
    """Durable repository for one business's commercial trial start."""

    def __init__(self, database: SQLiteDatabase) -> None:
        if not isinstance(database, SQLiteDatabase):
            raise TypeError("database must be a SQLiteDatabase.")
        self._database = database

    def save(self, trial: BusinessTrial) -> BusinessTrial:
        if not isinstance(trial, BusinessTrial):
            raise TypeError("trial must be a BusinessTrial.")
        with self._database.connection() as connection:
            connection.execute(
                "INSERT INTO business_trials(business_id, started_at) VALUES (?, ?) ON CONFLICT(business_id) DO UPDATE SET started_at=excluded.started_at",
                (trial.business_id, datetime_to_storage(trial.started_at)),
            )
        return trial

    def get(self, business_id: str) -> BusinessTrial | None:
        if not isinstance(business_id, str) or not business_id.strip():
            raise ValueError("business_id must be a non-empty string.")
        with self._database.connection() as connection:
            row = connection.execute(
                "SELECT business_id, started_at FROM business_trials WHERE business_id = ?",
                (business_id,),
            ).fetchone()
        return BusinessTrial(row["business_id"], datetime_from_storage(row["started_at"])) if row else None
PY

cat > app/persistence/commercial_repository.py <<'PY'
from __future__ import annotations

import sqlite3
from decimal import Decimal

from app.commercial.purchase import VerifiedPurchase
from app.commercial.purchase_record import PurchaseRecord
from app.commercial.trial import BusinessTrial
from app.persistence.database import SQLiteDatabase
from app.persistence.serialization import datetime_from_storage


class SQLitePurchaseStore:
    """Durable purchase history repository with database uniqueness."""

    def __init__(self, database: SQLiteDatabase) -> None:
        if not isinstance(database, SQLiteDatabase):
            raise TypeError("database must be a SQLiteDatabase.")
        self._database = database

    def get(self, provider: str, provider_event_id: str) -> PurchaseRecord | None:
        _validate(provider, provider_event_id)
        with self._database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM purchase_records WHERE provider = ? AND provider_event_id = ?",
                (provider, provider_event_id),
            ).fetchone()
        return _from_row(row) if row else None

    def save(self, record: PurchaseRecord) -> None:
        if not isinstance(record, PurchaseRecord):
            raise TypeError("record must be a PurchaseRecord.")
        with self._database.connection() as connection:
            try:
                connection.execute(
                    "INSERT INTO purchase_records(provider, provider_event_id, business_id, amount, currency, paid_at, recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (record.provider, record.provider_event_id, record.business_id, str(record.purchase.amount),
                     record.purchase.currency, record.purchase.paid_at.isoformat(), record.recorded_at.isoformat()),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("Purchase record cannot be persisted.") from exc


def _from_row(row) -> PurchaseRecord:
    purchase = VerifiedPurchase(
        provider=row["provider"], provider_event_id=row["provider_event_id"], business_id=row["business_id"],
        amount=Decimal(row["amount"]), currency=row["currency"], paid_at=datetime_from_storage(row["paid_at"]),
    )
    return PurchaseRecord(purchase=purchase, recorded_at=datetime_from_storage(row["recorded_at"]))


def _validate(provider: object, event_id: object) -> None:
    if not isinstance(provider, str) or not provider.strip():
        raise ValueError("provider must be a non-empty string.")
    if not isinstance(event_id, str) or not event_id.strip():
        raise ValueError("provider_event_id must be a non-empty string.")
PY

cat > app/persistence/commercial_state_repository.py <<'PY'
from __future__ import annotations

from app.commercial.state import BusinessCommercialState, CommercialStatus
from app.persistence.database import SQLiteDatabase


class SQLiteCommercialStateRepository:
    """Durable repository for business commercial lifecycle state."""

    def __init__(self, database: SQLiteDatabase) -> None:
        if not isinstance(database, SQLiteDatabase):
            raise TypeError("database must be a SQLiteDatabase.")
        self._database = database

    def save(self, state: BusinessCommercialState) -> BusinessCommercialState:
        if not isinstance(state, BusinessCommercialState):
            raise TypeError("state must be a BusinessCommercialState.")
        with self._database.connection() as connection:
            connection.execute(
                "INSERT INTO commercial_states(business_id, status) VALUES (?, ?) ON CONFLICT(business_id) DO UPDATE SET status=excluded.status",
                (state.business_id, state.status.value),
            )
        return state

    def get(self, business_id: str) -> BusinessCommercialState | None:
        _validate_id(business_id)
        with self._database.connection() as connection:
            row = connection.execute(
                "SELECT business_id, status FROM commercial_states WHERE business_id = ?",
                (business_id,),
            ).fetchone()
        return BusinessCommercialState(row["business_id"], CommercialStatus(row["status"])) if row else None


def _validate_id(value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("identifier must be a non-empty string.")
    if len(value) > 128:
        raise ValueError("identifier exceeds the maximum allowed length.")
PY

cat > app/persistence/launch_repository.py <<'PY'
from __future__ import annotations

from app.commercial.launch import LaunchProgram
from app.persistence.database import SQLiteDatabase


class SQLiteLaunchProgramRepository:
    """Durable repository for launch-program accounting."""

    def __init__(self, database: SQLiteDatabase) -> None:
        if not isinstance(database, SQLiteDatabase):
            raise TypeError("database must be a SQLiteDatabase.")
        self._database = database

    def get(self) -> LaunchProgram:
        with self._database.connection() as connection:
            row = connection.execute(
                "SELECT target_businesses, paid_businesses FROM launch_program WHERE singleton_id = 1"
            ).fetchone()
        if row is None:
            raise RuntimeError("launch_program state is missing.")
        return LaunchProgram(row["target_businesses"], row["paid_businesses"])

    def set_target(self, target_businesses: int) -> LaunchProgram:
        current = self.get()
        updated = LaunchProgram(target_businesses, current.paid_businesses)
        with self._database.connection() as connection:
            connection.execute(
                "UPDATE launch_program SET target_businesses = ? WHERE singleton_id = 1",
                (updated.target_businesses,),
            )
        return updated
PY

cat > app/persistence/commercial_transaction.py <<'PY'
from __future__ import annotations

import sqlite3

from app.commercial.purchase_record import PurchaseRecord
from app.commercial.trial import BusinessTrial
from app.persistence.database import SQLiteDatabase
from app.persistence.serialization import datetime_to_storage


class SQLiteCommercialTransaction:
    """Database transaction implementing the existing commercial contract."""

    def __init__(self, database: SQLiteDatabase) -> None:
        if not isinstance(database, SQLiteDatabase):
            raise TypeError("database must be a SQLiteDatabase.")
        self._database = database
        self._connection_context = database.connection()
        self._connection = self._connection_context.__enter__()
        self._completed = False
        try:
            self._connection.execute("BEGIN IMMEDIATE")
        except Exception:
            self._connection_context.__exit__(*__import__("sys").exc_info())
            self._connection = None
            self._completed = True
            raise

    def _ensure_open(self) -> sqlite3.Connection:
        if self._completed or self._connection is None:
            raise RuntimeError("Transaction is already completed.")
        return self._connection

    def record_purchase_once(self, record: PurchaseRecord) -> bool:
        connection = self._ensure_open()
        if not isinstance(record, PurchaseRecord):
            raise TypeError("record must be a PurchaseRecord.")
        try:
            connection.execute(
                "INSERT INTO purchase_records(provider, provider_event_id, business_id, amount, currency, paid_at, recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (record.provider, record.provider_event_id, record.business_id, str(record.purchase.amount),
                 record.purchase.currency, datetime_to_storage(record.purchase.paid_at),
                 datetime_to_storage(record.recorded_at)),
            )
            return True
        except sqlite3.IntegrityError:
            exists = connection.execute(
                "SELECT 1 FROM purchase_records WHERE provider = ? AND provider_event_id = ?",
                (record.provider, record.provider_event_id),
            ).fetchone()
            if exists is not None:
                return False
            raise ValueError("Verified purchase cannot be persisted.")

    def activate_business(self, business_id: str) -> None:
        connection = self._ensure_open()
        _validate_id(business_id)
        if connection.execute("SELECT 1 FROM businesses WHERE business_id = ?", (business_id,)).fetchone() is None:
            raise ValueError("business_id does not reference an existing business.")
        connection.execute(
            "INSERT INTO commercial_states(business_id, status) VALUES (?, 'active') ON CONFLICT(business_id) DO UPDATE SET status='active'",
            (business_id,),
        )

    def record_paid_business(self, business_id: str) -> None:
        connection = self._ensure_open()
        _validate_id(business_id)
        if connection.execute("SELECT 1 FROM businesses WHERE business_id = ?", (business_id,)).fetchone() is None:
            raise ValueError("business_id does not reference an existing business.")
        inserted = connection.execute(
            "INSERT OR IGNORE INTO paid_business_ledger(business_id) VALUES (?)",
            (business_id,),
        ).rowcount
        if inserted == 1:
            connection.execute(
                "UPDATE launch_program SET paid_businesses = MIN(target_businesses, paid_businesses + 1) WHERE singleton_id = 1"
            )

    def commit(self) -> None:
        connection = self._ensure_open()
        try:
            connection.commit()
        finally:
            self._close()

    def rollback(self) -> None:
        connection = self._ensure_open()
        try:
            connection.rollback()
        finally:
            self._close()

    def has_purchase(self, provider: str, provider_event_id: str) -> bool:
        connection = self._ensure_open()
        _validate_id(provider)
        _validate_id(provider_event_id)
        return connection.execute(
            "SELECT 1 FROM purchase_records WHERE provider = ? AND provider_event_id = ?",
            (provider, provider_event_id),
        ).fetchone() is not None

    def is_business_active(self, business_id: str) -> bool:
        connection = self._ensure_open()
        _validate_id(business_id)
        return connection.execute(
            "SELECT 1 FROM commercial_states WHERE business_id = ? AND status = 'active'",
            (business_id,),
        ).fetchone() is not None

    def is_paid_business(self, business_id: str) -> bool:
        connection = self._ensure_open()
        _validate_id(business_id)
        return connection.execute(
            "SELECT 1 FROM paid_business_ledger WHERE business_id = ?",
            (business_id,),
        ).fetchone() is not None

    def _close(self) -> None:
        if self._completed:
            return
        self._completed = True
        self._connection = None
        self._connection_context.__exit__(None, None, None)


def _validate_id(value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("identifier must be a non-empty string.")
    if len(value) > 128:
        raise ValueError("identifier exceeds the maximum allowed length.")
PY

cat > app/persistence/commercial_transaction_factory.py <<'PY'
from __future__ import annotations

from app.persistence.commercial_transaction import SQLiteCommercialTransaction
from app.persistence.database import SQLiteDatabase


class SQLiteCommercialTransactionFactory:
    """Create fresh durable commercial transactions."""

    def __init__(self, database: SQLiteDatabase) -> None:
        if not isinstance(database, SQLiteDatabase):
            raise TypeError("database must be a SQLiteDatabase.")
        self._database = database

    def begin(self) -> SQLiteCommercialTransaction:
        return SQLiteCommercialTransaction(self._database)
PY

cat > tests/test_sqlite_persistence.py <<'PY'
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.commercial.purchase import VerifiedPurchase
from app.commercial.purchase_record import PurchaseRecord
from app.commercial.trial import BusinessTrial
from app.identity import BusinessMembership, User, UserRole
from app.models.business import Business
from app.models.memory import Memory
from app.persistence.business_repository import SQLiteBusinessRepository
from app.persistence.commercial_repository import SQLitePurchaseStore
from app.persistence.commercial_state_repository import SQLiteCommercialStateRepository
from app.persistence.commercial_transaction_factory import SQLiteCommercialTransactionFactory
from app.persistence.database import SQLiteDatabase
from app.persistence.launch_repository import SQLiteLaunchProgramRepository
from app.persistence.memory_repository import SQLiteMemoryRepository
from app.persistence.membership_repository import SQLiteMembershipRepository
from app.persistence.session import SessionRecord, SQLiteSessionRepository
from app.persistence.trial_repository import SQLiteTrialRepository
from app.persistence.user_repository import SQLiteUserRepository
from app.persistence.trial_repository import SQLiteTrialRepository
from app.commercial.purchase_application import CommercialPurchaseService

NOW = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


def make_database(tmp_path):
    db = SQLiteDatabase(tmp_path / "assistant.sqlite3")
    db.initialize()
    return db


def make_business(business_id="business-1"):
    return Business(business_id, "Acme", "Owner", "Configured Test Assistant", "male")


def test_schema_and_business_survive_restart(tmp_path):
    db = make_database(tmp_path)
    SQLiteBusinessRepository(db).save(make_business())
    reopened = SQLiteDatabase(tmp_path / "assistant.sqlite3")
    reopened.initialize()
    assert SQLiteBusinessRepository(reopened).get("business-1") == make_business()


def test_user_email_unique_case_insensitively(tmp_path):
    db = make_database(tmp_path)
    repo = SQLiteUserRepository(db)
    repo.save(User("u1", "One", "Owner@example.com"))
    with pytest.raises(Exception):
        repo.save(User("u2", "Two", "owner@EXAMPLE.com"))


def test_membership_requires_existing_parents(tmp_path):
    db = make_database(tmp_path)
    with pytest.raises(Exception):
        SQLiteMembershipRepository(db).save(BusinessMembership("u", "b", UserRole.OWNER))
    SQLiteUserRepository(db).save(User("u", "Owner", "owner@example.com"))
    SQLiteBusinessRepository(db).save(make_business("b"))
    membership = BusinessMembership("u", "b", UserRole.OWNER)
    assert SQLiteMembershipRepository(db).save(membership) == membership


def test_memory_round_trip_and_tenant_filter(tmp_path):
    db = make_database(tmp_path)
    businesses = SQLiteBusinessRepository(db)
    businesses.save(make_business("a"))
    businesses.save(make_business("b"))
    repo = SQLiteMemoryRepository(db)
    first = Memory("m-a", "a", "secret-a", "business_rule", 5)
    second = Memory("m-b", "b", "secret-b", "business_rule", 5)
    repo.save(first)
    repo.save(second)
    assert repo.get("m-a") == first
    assert repo.list_for_business("a") == [first]
    assert repo.delete("m-a") is True


def test_memory_cannot_reference_unknown_business(tmp_path):
    db = make_database(tmp_path)
    with pytest.raises(ValueError):
        SQLiteMemoryRepository(db).save(Memory("m", "missing", "no", "business_rule", 1))


def test_trial_start_survives_restart(tmp_path):
    db = make_database(tmp_path)
    SQLiteBusinessRepository(db).save(make_business())
    trial = BusinessTrial("business-1", NOW)
    SQLiteTrialRepository(db).save(trial)
    reopened = SQLiteDatabase(tmp_path / "assistant.sqlite3")
    reopened.initialize()
    assert SQLiteTrialRepository(reopened).get("business-1") == trial


def test_session_round_trip_and_immediate_revoke(tmp_path):
    db = make_database(tmp_path)
    SQLiteUserRepository(db).save(User("u", "Owner", "owner@example.com"))
    SQLiteBusinessRepository(db).save(make_business("b"))
    session = SessionRecord("hash", "u", "b", UserRole.OWNER, NOW, NOW + timedelta(hours=1), NOW)
    repo = SQLiteSessionRepository(db)
    assert repo.save(session) == session
    assert repo.get("hash") == session
    assert repo.revoke("hash", NOW + timedelta(minutes=1)) is True
    assert repo.revoke("hash", NOW + timedelta(minutes=2)) is False


def test_purchase_history_survives_restart_and_is_unique(tmp_path):
    db = make_database(tmp_path)
    SQLiteBusinessRepository(db).save(make_business())
    purchase = VerifiedPurchase("provider", "event", "business-1", Decimal("100.00"), "ZAR", NOW)
    record = PurchaseRecord(purchase, NOW)
    repo = SQLitePurchaseStore(db)
    repo.save(record)
    with pytest.raises(ValueError):
        repo.save(record)
    reopened = SQLiteDatabase(tmp_path / "assistant.sqlite3")
    reopened.initialize()
    assert SQLitePurchaseStore(reopened).get("provider", "event") == record


def test_commercial_purchase_is_atomic_and_paid_business_is_counted_once(tmp_path):
    db = make_database(tmp_path)
    SQLiteBusinessRepository(db).save(make_business())
    service = CommercialPurchaseService(SQLiteCommercialTransactionFactory(db))
    purchase = VerifiedPurchase("provider", "event-1", "business-1", Decimal("25.00"), "ZAR", NOW)
    assert service.process(purchase, NOW).processed is True
    assert SQLiteCommercialStateRepository(db).get("business-1").status.value == "active"
    assert SQLiteLaunchProgramRepository(db).get().paid_businesses == 1
    assert service.process(purchase, NOW).duplicate is True
    assert SQLiteLaunchProgramRepository(db).get().paid_businesses == 1
PY

cat > tests/test_sqlite_persistence_attack.py <<'PY'
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.commercial.purchase import VerifiedPurchase
from app.commercial.purchase_application import CommercialPurchaseService
from app.identity import BusinessMembership, UserRole
from app.models.business import Business
from app.models.memory import Memory
from app.persistence.business_repository import SQLiteBusinessRepository
from app.persistence.commercial_transaction_factory import SQLiteCommercialTransactionFactory
from app.persistence.database import SQLiteDatabase
from app.persistence.memory_repository import SQLiteMemoryRepository
from app.persistence.membership_repository import SQLiteMembershipRepository
from app.persistence.session import SessionRecord, SQLiteSessionRepository
from app.persistence.trial_repository import SQLiteTrialRepository

NOW = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


def make_db(tmp_path):
    db = SQLiteDatabase(tmp_path / "attack.sqlite3")
    db.initialize()
    return db


def make_business(business_id):
    return Business(business_id, business_id, "Owner", "Configured Test Assistant", "female")


def test_cross_tenant_memory_filter_is_enforced_at_repository_boundary(tmp_path):
    db = make_db(tmp_path)
    businesses = SQLiteBusinessRepository(db)
    businesses.save(make_business("a"))
    businesses.save(make_business("b"))
    repo = SQLiteMemoryRepository(db)
    repo.save(Memory("m-a", "a", "secret-a", "business_rule", 5))
    repo.save(Memory("m-b", "b", "secret-b", "business_rule", 5))
    assert [m.memory_id for m in repo.list_for_business("a")] == ["m-a"]


def test_membership_parent_integrity_blocks_orphan_authorization(tmp_path):
    with pytest.raises(Exception):
        SQLiteMembershipRepository(make_db(tmp_path)).save(BusinessMembership("u", "b", UserRole.OWNER))


def test_trial_parent_integrity_blocks_orphan_trial(tmp_path):
    from app.commercial.trial import BusinessTrial
    with pytest.raises(Exception):
        SQLiteTrialRepository(make_db(tmp_path)).save(BusinessTrial("missing", NOW))


def test_session_parent_integrity_blocks_orphan_session(tmp_path):
    db = make_db(tmp_path)
    session = SessionRecord("hash", "u", "b", UserRole.OWNER, NOW, NOW, NOW)
    with pytest.raises(Exception):
        SQLiteSessionRepository(db).save(session)


def test_commercial_transaction_rolls_back_purchase_when_activation_fails(tmp_path):
    db = make_db(tmp_path)
    SQLiteBusinessRepository(db).save(make_business("b"))
    with db.connection() as connection:
        connection.execute(
            "CREATE TRIGGER fail_activation BEFORE INSERT ON commercial_states "
            "BEGIN SELECT RAISE(ABORT, 'forced activation failure'); END"
        )
    purchase = VerifiedPurchase("provider", "event", "b", Decimal("25.00"), "ZAR", NOW)
    with pytest.raises(Exception):
        CommercialPurchaseService(SQLiteCommercialTransactionFactory(db)).process(purchase, NOW)
    with db.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM purchase_records").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM commercial_states").fetchone()[0] == 0
PY

python -m compileall -q app/persistence tests/test_sqlite_persistence.py tests/test_sqlite_persistence_attack.py

echo "Persistence implementation installed. Run the Step 0 tests from the project environment next."
