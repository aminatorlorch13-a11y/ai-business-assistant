from __future__ import annotations

from datetime import datetime, timezone

from app.assistant.conversation import (
    ConversationHistory,
    ConversationRole,
    ConversationTurn,
)
from app.persistence.database import SQLiteDatabase


class SQLiteWebConversationRepository:
    """Durable conversation history isolated by authenticated user and business."""

    def __init__(self, database: SQLiteDatabase) -> None:
        if not isinstance(database, SQLiteDatabase):
            raise TypeError("database must be a SQLiteDatabase.")
        self._database = database

    def load_history(
        self,
        *,
        user_id: str,
        business_id: str,
    ) -> ConversationHistory:
        _validate_identifier(user_id, "user_id")
        _validate_identifier(business_id, "business_id")

        with self._database.connection() as connection:
            _require_membership(connection, user_id, business_id)
            rows = connection.execute(
                """
                SELECT business_id, role, content
                FROM web_conversation_turns
                WHERE user_id = ? AND business_id = ?
                ORDER BY sequence ASC
                """,
                (user_id, business_id),
            ).fetchall()

        turns = tuple(
            ConversationTurn(
                business_id=row["business_id"],
                role=ConversationRole(row["role"]),
                content=row["content"],
            )
            for row in rows
        )
        return ConversationHistory(
            business_id=business_id,
            turns=turns,
        )

    def append_exchange(
        self,
        *,
        user_id: str,
        business_id: str,
        user_content: str,
        assistant_content: str,
        created_at: datetime,
    ) -> ConversationHistory:
        """Atomically persist a successful exchange and retain complete exchanges."""
        _validate_identifier(user_id, "user_id")
        _validate_identifier(business_id, "business_id")
        _validate_content(user_content, "user_content")
        _validate_content(assistant_content, "assistant_content")

        if (
            not isinstance(created_at, datetime)
            or created_at.tzinfo is None
            or created_at.utcoffset() is None
        ):
            raise ValueError("created_at must be timezone-aware.")

        timestamp = created_at.astimezone(timezone.utc).isoformat()

        with self._database.transaction() as connection:
            _require_membership(connection, user_id, business_id)

            row = connection.execute(
                """
                SELECT COALESCE(MAX(sequence), 0) AS maximum_sequence
                FROM web_conversation_turns
                WHERE user_id = ? AND business_id = ?
                """,
                (user_id, business_id),
            ).fetchone()
            next_sequence = int(row["maximum_sequence"]) + 1

            connection.executemany(
                """
                INSERT INTO web_conversation_turns(
                    user_id, business_id, sequence, role, content, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        user_id,
                        business_id,
                        next_sequence,
                        ConversationRole.USER.value,
                        user_content,
                        timestamp,
                    ),
                    (
                        user_id,
                        business_id,
                        next_sequence + 1,
                        ConversationRole.ASSISTANT.value,
                        assistant_content,
                        timestamp,
                    ),
                ),
            )

        return self.load_history(
            user_id=user_id,
            business_id=business_id,
        )


def _require_membership(connection, user_id: str, business_id: str) -> None:
    row = connection.execute(
        """
        SELECT 1
        FROM business_memberships
        WHERE user_id = ? AND business_id = ?
        """,
        (user_id, business_id),
    ).fetchone()
    if row is None:
        raise PermissionError(
            "User does not belong to the supplied business."
        )


def _validate_identifier(value: object, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string.")
    if len(value) > 128:
        raise ValueError(f"{name} exceeds the maximum allowed length.")


def _validate_content(value: object, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string.")
