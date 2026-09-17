from __future__ import annotations

from datetime import datetime

from app.assistant.conversation import (
    ConversationHistory,
    ConversationRole,
    ConversationTurn,
    DEFAULT_MAX_CONVERSATION_TURNS,
)
from app.persistence.database import SQLiteDatabase
from app.persistence.serialization import datetime_to_storage


class SQLiteWhatsAppConversationRepository:
    """
    Durable conversation storage for one trusted WhatsApp binding.

    Conversation identity is binding-scoped, not merely business-scoped.
    This prevents multiple WhatsApp users belonging to the same business
    from sharing conversation history.

    The repository reconstructs the existing Phase-B ConversationHistory
    abstraction rather than creating a parallel AI context system.
    """

    def __init__(self, database: SQLiteDatabase) -> None:
        if not isinstance(database, SQLiteDatabase):
            raise TypeError("database must be a SQLiteDatabase.")
        self._database = database

    def load_history(
        self,
        *,
        binding_id: str,
        business_id: str,
        max_turns: int = DEFAULT_MAX_CONVERSATION_TURNS,
    ) -> ConversationHistory:
        _validate_identifier(binding_id, "binding_id")
        _validate_identifier(business_id, "business_id")
        _validate_max_turns(max_turns)

        with self._database.connection() as connection:
            _require_active_binding(
                connection,
                binding_id=binding_id,
                business_id=business_id,
            )

            rows = connection.execute(
                """
                SELECT
                    business_id,
                    role,
                    content
                FROM whatsapp_conversation_turns
                WHERE binding_id = ?
                  AND business_id = ?
                ORDER BY sequence DESC
                LIMIT ?
                """,
                (binding_id, business_id, max_turns),
            ).fetchall()

        rows = list(reversed(rows))

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
            max_turns=max_turns,
        )

    def append_exchange(
        self,
        *,
        binding_id: str,
        business_id: str,
        user_content: str,
        assistant_content: str,
        created_at: datetime,
        max_turns: int = DEFAULT_MAX_CONVERSATION_TURNS,
        exchange_id: str | None = None,
    ) -> ConversationHistory:
        """
        Atomically append one successful user/assistant exchange.

        The database transaction protects sequence allocation from concurrent
        writers. The user and assistant turns are inserted together.

        History is bounded by complete exchanges, never by an arbitrary
        number of individual rows.
        """
        _validate_identifier(binding_id, "binding_id")
        _validate_identifier(business_id, "business_id")

        if not isinstance(user_content, str) or not user_content.strip():
            raise ValueError("user_content must be a non-empty string.")

        if not isinstance(assistant_content, str) or not assistant_content.strip():
            raise ValueError("assistant_content must be a non-empty string.")

        if (
            not isinstance(created_at, datetime)
            or created_at.tzinfo is None
            or created_at.utcoffset() is None
        ):
            raise ValueError("created_at must be timezone-aware.")

        _validate_max_turns(max_turns)

        if exchange_id is not None:
            if not isinstance(exchange_id, str) or not exchange_id.strip():
                raise ValueError("exchange_id must be non-empty when supplied.")
            if len(exchange_id) > 512:
                raise ValueError("exchange_id is too long.")

        created_at_storage = datetime_to_storage(created_at)

        with self._database.transaction() as connection:
            _require_active_binding(
                connection,
                binding_id=binding_id,
                business_id=business_id,
            )

            row = connection.execute(
                """
                SELECT COALESCE(MAX(sequence), 0) AS maximum_sequence
                FROM whatsapp_conversation_turns
                WHERE binding_id = ?
                  AND business_id = ?
                """,
                (binding_id, business_id),
            ).fetchone()

            next_sequence = int(row["maximum_sequence"]) + 1

            if exchange_id is not None:
                existing = connection.execute(
                    """
                    SELECT 1
                    FROM whatsapp_conversation_turns
                    WHERE binding_id = ?
                      AND exchange_id = ?
                    LIMIT 1
                    """,
                    (binding_id, exchange_id),
                ).fetchone()

                if existing is not None:
                    rows = connection.execute(
                        """
                        SELECT business_id, role, content
                        FROM whatsapp_conversation_turns
                        WHERE binding_id = ?
                          AND business_id = ?
                        ORDER BY sequence ASC
                        """,
                        (binding_id, business_id),
                    ).fetchall()

                    return ConversationHistory(
                        business_id=business_id,
                        turns=tuple(
                            ConversationTurn(
                                business_id=row["business_id"],
                                role=ConversationRole(row["role"]),
                                content=row["content"],
                            )
                            for row in rows
                        ),
                        max_turns=max_turns,
                    )

            connection.execute(
                """
                INSERT INTO whatsapp_conversation_turns(
                    binding_id,
                    business_id,
                    sequence,
                    role,
                    content,
                    created_at,
                    exchange_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    binding_id,
                    business_id,
                    next_sequence,
                    ConversationRole.USER.value,
                    user_content,
                    created_at_storage,
                    exchange_id,
                ),
            )

            connection.execute(
                """
                INSERT INTO whatsapp_conversation_turns(
                    binding_id,
                    business_id,
                    sequence,
                    role,
                    content,
                    created_at,
                    exchange_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    binding_id,
                    business_id,
                    next_sequence + 1,
                    ConversationRole.ASSISTANT.value,
                    assistant_content,
                    created_at_storage,
                    None,
                ),
            )

            # Retain only the newest complete exchanges.
            keep_rows = max_turns

            connection.execute(
                """
                DELETE FROM whatsapp_conversation_turns
                WHERE binding_id = ?
                  AND business_id = ?
                  AND sequence NOT IN (
                      SELECT sequence
                      FROM whatsapp_conversation_turns
                      WHERE binding_id = ?
                        AND business_id = ?
                      ORDER BY sequence DESC
                      LIMIT ?
                  )
                """,
                (
                    binding_id,
                    business_id,
                    binding_id,
                    business_id,
                    keep_rows,
                ),
            )

            rows = connection.execute(
                """
                SELECT
                    business_id,
                    role,
                    content
                FROM whatsapp_conversation_turns
                WHERE binding_id = ?
                  AND business_id = ?
                ORDER BY sequence ASC
                """,
                (binding_id, business_id),
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
                max_turns=max_turns,
            )


def _require_active_binding(
    connection,
    *,
    binding_id: str,
    business_id: str,
) -> None:
    row = connection.execute(
        """
        SELECT business_id, active
        FROM whatsapp_bindings
        WHERE binding_id = ?
        """,
        (binding_id,),
    ).fetchone()

    if row is None:
        raise PermissionError("WhatsApp binding does not exist.")

    if row["business_id"] != business_id:
        raise PermissionError(
            "WhatsApp binding does not belong to the supplied business."
        )

    if int(row["active"]) != 1:
        raise PermissionError("WhatsApp binding is inactive.")


def _validate_identifier(value: object, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string.")

    if len(value) > 128:
        raise ValueError(f"{name} exceeds the maximum allowed length.")


def _validate_max_turns(max_turns: object) -> None:
    if not isinstance(max_turns, int) or isinstance(max_turns, bool):
        raise TypeError("max_turns must be an integer.")

    if max_turns < 2:
        raise ValueError("max_turns must be at least 2.")

    if max_turns % 2 != 0:
        raise ValueError("max_turns must be even.")
