from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.identity.models import SessionScope, UserRole
from app.persistence.database import SQLiteDatabase


@dataclass(frozen=True)
class SessionRecord:
    """Durable server-side session state.

    BUSINESS sessions belong to one customer tenant and carry a business
    role. PLATFORM sessions represent platform-level Founder authority and
    therefore carry no business or customer role.
    """

    session_id_hash: str
    user_id: str
    scope: SessionScope
    business_id: str | None
    role: UserRole | None
    created_at: datetime
    expires_at: datetime
    last_seen_at: datetime
    revoked_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.session_id_hash:
            raise ValueError("session_id_hash must not be empty.")

        if not self.user_id:
            raise ValueError("user_id must not be empty.")

        if not isinstance(self.scope, SessionScope):
            raise TypeError("scope must be a SessionScope.")

        if self.scope is SessionScope.BUSINESS:
            if not self.business_id:
                raise ValueError(
                    "business_id is required for a BUSINESS session."
                )

            if not isinstance(self.role, UserRole):
                raise TypeError(
                    "role must be a UserRole for a BUSINESS session."
                )

        elif self.scope is SessionScope.PLATFORM:
            if self.business_id is not None:
                raise ValueError(
                    "business_id must be None for a PLATFORM session."
                )

            if self.role is not None:
                raise ValueError(
                    "role must be None for a PLATFORM session."
                )

        for name, value in (
            ("created_at", self.created_at),
            ("expires_at", self.expires_at),
            ("last_seen_at", self.last_seen_at),
        ):
            if value.tzinfo is None:
                raise ValueError(f"{name} must be timezone-aware.")

        if self.revoked_at is not None and self.revoked_at.tzinfo is None:
            raise ValueError("revoked_at must be timezone-aware.")


class SQLiteSessionRepository:
    """SQLite-backed repository for opaque server-side sessions."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    def save(self, session: SessionRecord) -> None:
        """Create or replace the complete durable state for a session."""
        with self._database.connection() as connection:
            connection.execute(
                """
                INSERT INTO sessions (
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
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id_hash) DO UPDATE SET
                    user_id = excluded.user_id,
                    scope = excluded.scope,
                    business_id = excluded.business_id,
                    role = excluded.role,
                    created_at = excluded.created_at,
                    expires_at = excluded.expires_at,
                    last_seen_at = excluded.last_seen_at,
                    revoked_at = excluded.revoked_at
                """,
                (
                    session.session_id_hash,
                    session.user_id,
                    session.scope.value,
                    session.business_id,
                    session.role.value if session.role is not None else None,
                    session.created_at.isoformat(),
                    session.expires_at.isoformat(),
                    session.last_seen_at.isoformat(),
                    (
                        session.revoked_at.isoformat()
                        if session.revoked_at is not None
                        else None
                    ),
                ),
            )

    def get(self, session_id_hash: str) -> SessionRecord | None:
        with self._database.connection() as connection:
            row = connection.execute(
                """
                SELECT
                    session_id_hash,
                    user_id,
                    scope,
                    business_id,
                    role,
                    created_at,
                    expires_at,
                    last_seen_at,
                    revoked_at
                FROM sessions
                WHERE session_id_hash = ?
                """,
                (session_id_hash,),
            ).fetchone()

        if row is None:
            return None

        return self._from_row(row)

    def revoke(self, session_id_hash: str, revoked_at: datetime) -> None:
        if revoked_at.tzinfo is None:
            raise ValueError("revoked_at must be timezone-aware.")

        with self._database.connection() as connection:
            connection.execute(
                """
                UPDATE sessions
                SET revoked_at = ?
                WHERE session_id_hash = ?
                """,
                (revoked_at.isoformat(), session_id_hash),
            )

    @staticmethod
    def _from_row(row) -> SessionRecord:
        scope = SessionScope(row["scope"])

        role = (
            UserRole(row["role"])
            if row["role"] is not None
            else None
        )

        return SessionRecord(
            session_id_hash=row["session_id_hash"],
            user_id=row["user_id"],
            scope=scope,
            business_id=row["business_id"],
            role=role,
            created_at=datetime.fromisoformat(row["created_at"]),
            expires_at=datetime.fromisoformat(row["expires_at"]),
            last_seen_at=datetime.fromisoformat(row["last_seen_at"]),
            revoked_at=(
                datetime.fromisoformat(row["revoked_at"])
                if row["revoked_at"] is not None
                else None
            ),
        )
