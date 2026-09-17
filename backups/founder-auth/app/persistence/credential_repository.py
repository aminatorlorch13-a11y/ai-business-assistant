from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.persistence.database import SQLiteDatabase
from app.persistence.serialization import datetime_from_storage, datetime_to_storage


@dataclass(frozen=True)
class CredentialRecord:
    user_id: str
    credential_hash: str
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        _validate_id(self.user_id)
        if not isinstance(self.credential_hash, str) or not self.credential_hash.strip():
            raise ValueError("credential_hash must be a non-empty string.")
        for field_name, value in (("created_at", self.created_at), ("updated_at", self.updated_at)):
            if not isinstance(value, datetime):
                raise TypeError(f"{field_name} must be a datetime.")
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{field_name} must be timezone-aware.")


class SQLiteCredentialRepository:
    """Durable credential storage; password material is never stored directly."""

    def __init__(self, database: SQLiteDatabase) -> None:
        if not isinstance(database, SQLiteDatabase):
            raise TypeError("database must be a SQLiteDatabase.")
        self._database = database

    def get_by_user_id(self, user_id: str) -> CredentialRecord | None:
        _validate_id(user_id)
        with self._database.connection() as connection:
            row = connection.execute(
                "SELECT user_id, credential_hash, created_at, updated_at FROM credentials WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        return CredentialRecord(
            row["user_id"],
            row["credential_hash"],
            datetime_from_storage(row["created_at"]),
            datetime_from_storage(row["updated_at"]),
        )

    def save(self, user_id: str, credential_hash: str, *, at: datetime | None = None) -> CredentialRecord:
        _validate_id(user_id)
        if not isinstance(credential_hash, str) or not credential_hash.strip():
            raise ValueError("credential_hash must be a non-empty string.")
        now = _utc(at or datetime.now(timezone.utc))
        with self._database.connection() as connection:
            existing = connection.execute(
                "SELECT created_at FROM credentials WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            created_at = datetime_from_storage(existing["created_at"]) if existing else now
            connection.execute(
                """
                INSERT INTO credentials(user_id, credential_hash, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    credential_hash=excluded.credential_hash,
                    updated_at=excluded.updated_at
                """,
                (user_id, credential_hash, datetime_to_storage(created_at), datetime_to_storage(now)),
            )
        return CredentialRecord(user_id, credential_hash, created_at, now)


def _validate_id(value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("identifier must be a non-empty string.")
    if len(value) > 128:
        raise ValueError("identifier exceeds the maximum allowed length.")


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware.")
    return value.astimezone(timezone.utc)
