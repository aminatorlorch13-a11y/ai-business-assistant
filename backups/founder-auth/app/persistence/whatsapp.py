from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.delivery.state import DeliveryState
from app.identity.models import UserRole
from app.persistence.database import SQLiteDatabase
from app.persistence.serialization import (
    datetime_from_storage,
    datetime_to_storage,
)
from app.whatsapp.models import WhatsAppBinding


WhatsAppMessageStatus = DeliveryState


@dataclass(frozen=True)
class WhatsAppMessageRecord:
    provider: str
    provider_account_id: str
    provider_message_id: str
    sender_id_hash: str
    status: DeliveryState
    received_at: datetime

    business_id: str | None = None
    binding_id: str | None = None
    inbound_text: str | None = None

    completed_at: datetime | None = None
    delivery_attempted_at: datetime | None = None
    delivered_at: datetime | None = None
    conversation_persisted_at: datetime | None = None

    response_text: str | None = None
    error_code: str | None = None
    provider_response_message_id: str | None = None


class SQLiteWhatsAppRepository:
    """Durable WhatsApp identity and delivery state storage."""

    def __init__(self, database: SQLiteDatabase) -> None:
        if not isinstance(database, SQLiteDatabase):
            raise TypeError("database must be a SQLiteDatabase.")
        self._database = database

    def save_binding(self, binding: WhatsAppBinding) -> WhatsAppBinding:
        if not isinstance(binding, WhatsAppBinding):
            raise TypeError("binding must be a WhatsAppBinding.")

        with self._database.connection() as connection:
            connection.execute(
                """
                INSERT INTO whatsapp_bindings(
                    binding_id,
                    provider,
                    provider_account_id,
                    sender_id_hash,
                    user_id,
                    business_id,
                    role,
                    active
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(binding_id) DO UPDATE SET
                    provider=excluded.provider,
                    provider_account_id=excluded.provider_account_id,
                    sender_id_hash=excluded.sender_id_hash,
                    user_id=excluded.user_id,
                    business_id=excluded.business_id,
                    role=excluded.role,
                    active=excluded.active
                """,
                (
                    binding.binding_id,
                    binding.provider,
                    binding.provider_account_id,
                    binding.sender_id_hash,
                    binding.user_id,
                    binding.business_id,
                    binding.role.value,
                    int(binding.active),
                ),
            )

        return binding

    def get_binding(
        self,
        provider: str,
        provider_account_id: str,
        sender_id_hash: str,
    ) -> WhatsAppBinding | None:
        with self._database.connection() as connection:
            row = connection.execute(
                """
                SELECT
                    binding_id,
                    provider,
                    provider_account_id,
                    sender_id_hash,
                    user_id,
                    business_id,
                    role,
                    active
                FROM whatsapp_bindings
                WHERE provider = ?
                  AND provider_account_id = ?
                  AND sender_id_hash = ?
                """,
                (provider, provider_account_id, sender_id_hash),
            ).fetchone()

        if row is None:
            return None

        return WhatsAppBinding(
            binding_id=row["binding_id"],
            provider=row["provider"],
            provider_account_id=row["provider_account_id"],
            sender_id_hash=row["sender_id_hash"],
            user_id=row["user_id"],
            business_id=row["business_id"],
            role=UserRole(row["role"]),
            active=bool(row["active"]),
        )

    def deactivate_binding(self, binding_id: str) -> bool:
        if not isinstance(binding_id, str) or not binding_id.strip():
            raise ValueError("binding_id must be non-empty.")

        with self._database.connection() as connection:
            cursor = connection.execute(
                """
                UPDATE whatsapp_bindings
                SET active = 0
                WHERE binding_id = ? AND active = 1
                """,
                (binding_id,),
            )

        return cursor.rowcount == 1

    def claim_message(
        self,
        provider: str,
        provider_account_id: str,
        provider_message_id: str,
        sender_id_hash: str,
        received_at: datetime,
        *,
        business_id: str | None = None,
        binding_id: str | None = None,
        inbound_text: str | None = None,
    ) -> bool:
        if not isinstance(received_at, datetime) or received_at.tzinfo is None:
            raise ValueError("received_at must be timezone-aware.")

        with self._database.connection() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO whatsapp_inbound_messages(
                    provider,
                    provider_account_id,
                    provider_message_id,
                    sender_id_hash,
                    status,
                    received_at,
                    business_id,
                    binding_id,
                    inbound_text
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    provider,
                    provider_account_id,
                    provider_message_id,
                    sender_id_hash,
                    DeliveryState.PROCESSING.value,
                    datetime_to_storage(received_at),
                    business_id,
                    binding_id,
                    inbound_text,
                ),
            )

        return cursor.rowcount == 1

    def prepare_delivery(
        self,
        *,
        provider: str,
        provider_account_id: str,
        provider_message_id: str,
        business_id: str,
        binding_id: str,
        inbound_text: str,
        response_text: str,
    ) -> None:
        for name, value in {
            "business_id": business_id,
            "binding_id": binding_id,
            "inbound_text": inbound_text,
            "response_text": response_text,
        }.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be non-empty.")

        with self._database.connection() as connection:
            cursor = connection.execute(
                """
                UPDATE whatsapp_inbound_messages
                SET
                    status = ?,
                    business_id = ?,
                    binding_id = ?,
                    inbound_text = ?,
                    response_text = ?,
                    error_code = NULL
                WHERE provider = ?
                  AND provider_account_id = ?
                  AND provider_message_id = ?
                  AND status = ?
                """,
                (
                    DeliveryState.DELIVERY_PENDING.value,
                    business_id,
                    binding_id,
                    inbound_text,
                    response_text,
                    provider,
                    provider_account_id,
                    provider_message_id,
                    DeliveryState.PROCESSING.value,
                ),
            )

        if cursor.rowcount != 1:
            raise RuntimeError("WhatsApp delivery preparation failed.")

    def mark_delivery_attempted(
        self,
        *,
        provider: str,
        provider_account_id: str,
        provider_message_id: str,
        attempted_at: datetime,
    ) -> None:
        _require_aware(attempted_at)

        with self._database.connection() as connection:
            cursor = connection.execute(
                """
                UPDATE whatsapp_inbound_messages
                SET
                    status = ?,
                    delivery_attempted_at = ?
                WHERE provider = ?
                  AND provider_account_id = ?
                  AND provider_message_id = ?
                  AND status = ?
                  AND delivery_attempted_at IS NULL
                """,
                (
                    DeliveryState.DELIVERY_ATTEMPTED.value,
                    datetime_to_storage(attempted_at),
                    provider,
                    provider_account_id,
                    provider_message_id,
                    DeliveryState.DELIVERY_PENDING.value,
                ),
            )

        if cursor.rowcount != 1:
            raise RuntimeError("WhatsApp delivery attempt transition failed.")

    def mark_delivered(
        self,
        *,
        provider: str,
        provider_account_id: str,
        provider_message_id: str,
        delivered_at: datetime,
        provider_response_message_id: str,
    ) -> None:
        _require_aware(delivered_at)

        if (
            not isinstance(provider_response_message_id, str)
            or not provider_response_message_id.strip()
        ):
            raise ValueError("provider_response_message_id must be non-empty.")

        with self._database.connection() as connection:
            cursor = connection.execute(
                """
                UPDATE whatsapp_inbound_messages
                SET
                    status = ?,
                    delivered_at = ?,
                    provider_response_message_id = ?,
                    error_code = NULL
                WHERE provider = ?
                  AND provider_account_id = ?
                  AND provider_message_id = ?
                  AND status = ?
                """,
                (
                    DeliveryState.DELIVERED.value,
                    datetime_to_storage(delivered_at),
                    provider_response_message_id,
                    provider,
                    provider_account_id,
                    provider_message_id,
                    DeliveryState.DELIVERY_ATTEMPTED.value,
                ),
            )

        if cursor.rowcount != 1:
            raise RuntimeError("WhatsApp delivery confirmation failed.")

    def mark_conversation_persisted(
        self,
        *,
        provider: str,
        provider_account_id: str,
        provider_message_id: str,
        persisted_at: datetime,
    ) -> None:
        _require_aware(persisted_at)

        with self._database.connection() as connection:
            cursor = connection.execute(
                """
                UPDATE whatsapp_inbound_messages
                SET
                    status = ?,
                    conversation_persisted_at = ?
                WHERE provider = ?
                  AND provider_account_id = ?
                  AND provider_message_id = ?
                  AND status = ?
                """,
                (
                    DeliveryState.CONVERSATION_PERSISTED.value,
                    datetime_to_storage(persisted_at),
                    provider,
                    provider_account_id,
                    provider_message_id,
                    DeliveryState.DELIVERED.value,
                ),
            )

        if cursor.rowcount != 1:
            raise RuntimeError("WhatsApp conversation persistence transition failed.")

    def complete_message(
        self,
        *,
        provider: str,
        provider_account_id: str,
        provider_message_id: str,
        completed_at: datetime,
    ) -> None:
        _require_aware(completed_at)

        with self._database.connection() as connection:
            cursor = connection.execute(
                """
                UPDATE whatsapp_inbound_messages
                SET
                    status = ?,
                    completed_at = ?,
                    error_code = NULL
                WHERE provider = ?
                  AND provider_account_id = ?
                  AND provider_message_id = ?
                  AND status = ?
                """,
                (
                    DeliveryState.COMPLETED.value,
                    datetime_to_storage(completed_at),
                    provider,
                    provider_account_id,
                    provider_message_id,
                    DeliveryState.CONVERSATION_PERSISTED.value,
                ),
            )

        if cursor.rowcount != 1:
            raise RuntimeError("WhatsApp message completion state transition failed.")

    def fail_message(
        self,
        *,
        provider: str,
        provider_account_id: str,
        provider_message_id: str,
        completed_at: datetime,
        error_code: str,
    ) -> None:
        _require_aware(completed_at)

        if not isinstance(error_code, str) or not error_code.strip():
            raise ValueError("error_code must be non-empty.")

        with self._database.connection() as connection:
            cursor = connection.execute(
                """
                UPDATE whatsapp_inbound_messages
                SET
                    status = ?,
                    completed_at = ?,
                    error_code = ?
                WHERE provider = ?
                  AND provider_account_id = ?
                  AND provider_message_id = ?
                  AND status IN (?, ?)
                """,
                (
                    DeliveryState.FAILED.value,
                    datetime_to_storage(completed_at),
                    error_code,
                    provider,
                    provider_account_id,
                    provider_message_id,
                    DeliveryState.PROCESSING.value,
                    DeliveryState.DELIVERY_ATTEMPTED.value,
                ),
            )

        if cursor.rowcount != 1:
            raise RuntimeError("WhatsApp message failure state transition failed.")

    def mark_delivery_unknown(
        self,
        *,
        provider: str,
        provider_account_id: str,
        provider_message_id: str,
        error_code: str,
    ) -> None:
        if not isinstance(error_code, str) or not error_code.strip():
            raise ValueError("error_code must be non-empty.")

        with self._database.connection() as connection:
            cursor = connection.execute(
                """
                UPDATE whatsapp_inbound_messages
                SET
                    status = ?,
                    error_code = ?
                WHERE provider = ?
                  AND provider_account_id = ?
                  AND provider_message_id = ?
                  AND status IN (?, ?)
                """,
                (
                    DeliveryState.DELIVERY_UNKNOWN.value,
                    error_code,
                    provider,
                    provider_account_id,
                    provider_message_id,
                    DeliveryState.DELIVERY_ATTEMPTED.value,
                    DeliveryState.DELIVERY_PENDING.value,
                ),
            )

        if cursor.rowcount != 1:
            raise RuntimeError("WhatsApp delivery unknown transition failed.")

    def get_message(
        self,
        provider: str,
        provider_account_id: str,
        provider_message_id: str,
    ) -> WhatsAppMessageRecord | None:
        with self._database.connection() as connection:
            row = connection.execute(
                """
                SELECT
                    provider,
                    provider_account_id,
                    provider_message_id,
                    sender_id_hash,
                    status,
                    received_at,
                    business_id,
                    binding_id,
                    inbound_text,
                    completed_at,
                    delivery_attempted_at,
                    delivered_at,
                    conversation_persisted_at,
                    response_text,
                    error_code,
                    provider_response_message_id
                FROM whatsapp_inbound_messages
                WHERE provider = ?
                  AND provider_account_id = ?
                  AND provider_message_id = ?
                """,
                (
                    provider,
                    provider_account_id,
                    provider_message_id,
                ),
            ).fetchone()

        if row is None:
            return None

        return WhatsAppMessageRecord(
            provider=row["provider"],
            provider_account_id=row["provider_account_id"],
            provider_message_id=row["provider_message_id"],
            sender_id_hash=row["sender_id_hash"],
            status=DeliveryState(row["status"]),
            received_at=datetime_from_storage(row["received_at"]),
            business_id=row["business_id"],
            binding_id=row["binding_id"],
            inbound_text=row["inbound_text"],
            completed_at=(
                datetime_from_storage(row["completed_at"])
                if row["completed_at"]
                else None
            ),
            delivery_attempted_at=(
                datetime_from_storage(row["delivery_attempted_at"])
                if row["delivery_attempted_at"]
                else None
            ),
            delivered_at=(
                datetime_from_storage(row["delivered_at"])
                if row["delivered_at"]
                else None
            ),
            conversation_persisted_at=(
                datetime_from_storage(row["conversation_persisted_at"])
                if row["conversation_persisted_at"]
                else None
            ),
            response_text=row["response_text"],
            error_code=row["error_code"],
            provider_response_message_id=row["provider_response_message_id"],
        )


def _require_aware(value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("datetime must be timezone-aware.")
