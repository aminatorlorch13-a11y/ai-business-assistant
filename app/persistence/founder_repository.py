from __future__ import annotations

from app.founder.models import FounderRecord
from app.persistence.database import SQLiteDatabase


class SQLiteFounderRepository:
    """Durable repository for platform-level Founder authority."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    def get(self, user_id: str) -> FounderRecord | None:
        if not isinstance(user_id, str) or not user_id.strip():
            raise ValueError("user_id must be a non-empty string.")

        with self._database.connection() as connection:
            row = connection.execute(
                """
                SELECT user_id, active
                FROM platform_founders
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()

        if row is None:
            return None

        return FounderRecord(
            user_id=row["user_id"],
            active=bool(row["active"]),
        )

    def save(self, founder: FounderRecord) -> None:
        if not isinstance(founder, FounderRecord):
            raise TypeError("founder must be a FounderRecord.")

        with self._database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO platform_founders(user_id, active)
                VALUES(?, ?)
                ON CONFLICT(user_id)
                DO UPDATE SET active = excluded.active
                """,
                (founder.user_id, int(founder.active)),
            )

    def set_active(self, user_id: str, active: bool) -> None:
        if not isinstance(user_id, str) or not user_id.strip():
            raise ValueError("user_id must be a non-empty string.")

        if not isinstance(active, bool):
            raise TypeError("active must be a bool.")

        with self._database.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE platform_founders
                SET active = ?
                WHERE user_id = ?
                """,
                (int(active), user_id),
            )

            if cursor.rowcount == 0:
                raise LookupError("Founder record not found.")
