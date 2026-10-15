from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from app.assistant.conversation import (
    ConversationHistory,
    ConversationRole,
    ConversationTurn,
)
from app.persistence.database import SQLiteDatabase
from app.persistence.serialization import (
    datetime_from_storage,
    datetime_to_storage,
)


@dataclass(frozen=True)
class VoiceConversationRecord:
    conversation_id: str
    user_id: str
    business_id: str
    created_at: datetime
    updated_at: datetime


class SQLiteVoiceConversationRepository:
    """Durable voice history isolated by user, business, and conversation."""

    def __init__(self, database: SQLiteDatabase) -> None:
        if not isinstance(database, SQLiteDatabase):
            raise TypeError("database must be a SQLiteDatabase.")
        self._database = database

    def create_conversation(
        self,
        *,
        user_id: str,
        business_id: str,
        created_at: datetime,
        conversation_id: str | None = None,
    ) -> VoiceConversationRecord:
        _validate_identifier(user_id, "user_id")
        _validate_identifier(business_id, "business_id")
        _validate_datetime(created_at)

        identifier = (
            str(uuid4()) if conversation_id is None else conversation_id
        )
        _validate_identifier(identifier, "conversation_id")
        timestamp = datetime_to_storage(created_at)

        with self._database.transaction() as connection:
            _require_membership(
                connection,
                user_id=user_id,
                business_id=business_id,
            )
            connection.execute(
                """
                INSERT INTO voice_conversations(
                    conversation_id, user_id, business_id,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    identifier,
                    user_id,
                    business_id,
                    timestamp,
                    timestamp,
                ),
            )
            row = connection.execute(
                """
                SELECT conversation_id, user_id, business_id,
                       created_at, updated_at
                FROM voice_conversations
                WHERE conversation_id = ?
                """,
                (identifier,),
            ).fetchone()

        return _record_from_row(row)

    def list_conversations(
        self,
        *,
        user_id: str,
        business_id: str,
    ) -> tuple[VoiceConversationRecord, ...]:
        _validate_identifier(user_id, "user_id")
        _validate_identifier(business_id, "business_id")

        with self._database.connection() as connection:
            _require_membership(
                connection,
                user_id=user_id,
                business_id=business_id,
            )
            rows = connection.execute(
                """
                SELECT conversation_id, user_id, business_id,
                       created_at, updated_at
                FROM voice_conversations
                WHERE user_id = ? AND business_id = ?
                ORDER BY updated_at DESC, conversation_id ASC
                """,
                (user_id, business_id),
            ).fetchall()

        return tuple(_record_from_row(row) for row in rows)

    def load_history(
        self,
        *,
        user_id: str,
        business_id: str,
        conversation_id: str,
    ) -> ConversationHistory:
        _validate_identifier(user_id, "user_id")
        _validate_identifier(business_id, "business_id")
        _validate_identifier(conversation_id, "conversation_id")

        with self._database.connection() as connection:
            _require_owned_conversation(
                connection,
                user_id=user_id,
                business_id=business_id,
                conversation_id=conversation_id,
            )
            rows = connection.execute(
                """
                SELECT role, content
                FROM voice_conversation_turns
                WHERE conversation_id = ?
                ORDER BY sequence ASC
                """,
                (conversation_id,),
            ).fetchall()

        return ConversationHistory(
            business_id=business_id,
            turns=tuple(
                ConversationTurn(
                    business_id=business_id,
                    role=ConversationRole(row["role"]),
                    content=row["content"],
                )
                for row in rows
            ),
        )

    def append_exchange(
        self,
        *,
        user_id: str,
        business_id: str,
        conversation_id: str,
        user_content: str,
        assistant_content: str,
        created_at: datetime,
    ) -> ConversationHistory:
        """Persist a completed user/assistant exchange atomically."""
        _validate_identifier(user_id, "user_id")
        _validate_identifier(business_id, "business_id")
        _validate_identifier(conversation_id, "conversation_id")
        _validate_content(user_content, "user_content")
        _validate_content(assistant_content, "assistant_content")
        timestamp = _validated_timestamp(created_at)

        with self._database.transaction() as connection:
            _require_owned_conversation(
                connection,
                user_id=user_id,
                business_id=business_id,
                conversation_id=conversation_id,
            )
            row = connection.execute(
                """
                SELECT COALESCE(MAX(sequence), 0) AS maximum_sequence
                FROM voice_conversation_turns
                WHERE conversation_id = ?
                """,
                (conversation_id,),
            ).fetchone()
            sequence = int(row["maximum_sequence"]) + 1

            connection.execute(
                """
                INSERT INTO voice_conversation_turns(
                    conversation_id, sequence, role, content, created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    sequence,
                    ConversationRole.USER.value,
                    user_content,
                    timestamp,
                ),
            )
            connection.execute(
                """
                INSERT INTO voice_conversation_turns(
                    conversation_id, sequence, role, content, created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    sequence + 1,
                    ConversationRole.ASSISTANT.value,
                    assistant_content,
                    timestamp,
                ),
            )
            connection.execute(
                """
                UPDATE voice_conversations
                SET updated_at = ?
                WHERE conversation_id = ?
                """,
                (timestamp, conversation_id),
            )

        return self.load_history(
            user_id=user_id,
            business_id=business_id,
            conversation_id=conversation_id,
        )

    def append_turn(
        self,
        *,
        user_id: str,
        business_id: str,
        conversation_id: str,
        role: ConversationRole,
        content: str,
        created_at: datetime,
    ) -> ConversationHistory:
        """Persist one standalone turn, such as a confirmation response."""
        _validate_identifier(user_id, "user_id")
        _validate_identifier(business_id, "business_id")
        _validate_identifier(conversation_id, "conversation_id")

        if not isinstance(role, ConversationRole):
            raise TypeError("role must be a ConversationRole.")
        _validate_content(content, "content")
        timestamp = _validated_timestamp(created_at)

        with self._database.transaction() as connection:
            _require_owned_conversation(
                connection,
                user_id=user_id,
                business_id=business_id,
                conversation_id=conversation_id,
            )
            row = connection.execute(
                """
                SELECT COALESCE(MAX(sequence), 0) AS maximum_sequence
                FROM voice_conversation_turns
                WHERE conversation_id = ?
                """,
                (conversation_id,),
            ).fetchone()
            sequence = int(row["maximum_sequence"]) + 1

            connection.execute(
                """
                INSERT INTO voice_conversation_turns(
                    conversation_id, sequence, role, content, created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    sequence,
                    role.value,
                    content,
                    timestamp,
                ),
            )
            connection.execute(
                """
                UPDATE voice_conversations
                SET updated_at = ?
                WHERE conversation_id = ?
                """,
                (timestamp, conversation_id),
            )

        return self.load_history(
            user_id=user_id,
            business_id=business_id,
            conversation_id=conversation_id,
        )


def _require_membership(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    business_id: str,
) -> None:
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
            "User is not a member of the requested business."
        )


def _require_owned_conversation(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    business_id: str,
    conversation_id: str,
) -> None:
    _require_membership(
        connection,
        user_id=user_id,
        business_id=business_id,
    )
    row = connection.execute(
        """
        SELECT 1
        FROM voice_conversations
        WHERE conversation_id = ?
          AND user_id = ?
          AND business_id = ?
        """,
        (conversation_id, user_id, business_id),
    ).fetchone()

    if row is None:
        raise PermissionError(
            "Voice conversation does not belong to this user and business."
        )


def _record_from_row(row: sqlite3.Row) -> VoiceConversationRecord:
    return VoiceConversationRecord(
        conversation_id=row["conversation_id"],
        user_id=row["user_id"],
        business_id=row["business_id"],
        created_at=datetime_from_storage(row["created_at"]),
        updated_at=datetime_from_storage(row["updated_at"]),
    )


def _validate_identifier(value: object, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string.")
    if len(value) > 128:
        raise ValueError(f"{name} is too long.")


def _validate_content(value: object, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string.")


def _validate_datetime(value: object) -> None:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError("created_at must be timezone-aware.")


def _validated_timestamp(value: object) -> str:
    _validate_datetime(value)
    return datetime_to_storage(value)
