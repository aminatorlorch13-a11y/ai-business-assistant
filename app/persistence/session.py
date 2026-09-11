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
