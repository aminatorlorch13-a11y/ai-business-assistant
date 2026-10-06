from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Protocol

from app.assistant.capability import Capability
from app.assistant.capability_confirmation import CapabilityConfirmation
from app.assistant.execution import CapabilityExecutionRequest
from app.identity.models import UserRole
from app.persistence.database import SQLiteDatabase
from app.persistence.serialization import (
    datetime_from_storage,
    datetime_to_storage,
)


class CapabilityConfirmationRepository(Protocol):
    """Persistence boundary for durable capability confirmations."""

    def save_exclusive(
        self,
        confirmation: CapabilityConfirmation,
    ) -> None:
        ...

    def save(self, confirmation: CapabilityConfirmation) -> None:
        ...

    def get(self, confirmation_id: str) -> CapabilityConfirmation | None:
        ...

    def consume(
        self,
        confirmation_id: str,
        *,
        session_id_hash: str,
        user_id: str,
        business_id: str,
        role: UserRole,
        channel: str | None,
        integration: str | None,
        now: datetime,
    ) -> CapabilityConfirmation | None:
        ...

    def revoke(
        self,
        confirmation_id: str,
        *,
        session_id_hash: str,
        user_id: str,
        business_id: str,
        role: UserRole,
        channel: str | None,
        integration: str | None,
        now: datetime,
    ) -> bool:
        ...


class SQLiteCapabilityConfirmationRepository:
    """
    SQLite-backed durable capability confirmation store.

    Consumption is atomic. A confirmation can only transition from pending
    to consumed once, and only when its complete security binding matches
    the caller.
    """

    def __init__(self, database: SQLiteDatabase) -> None:
        if not isinstance(database, SQLiteDatabase):
            raise TypeError("database must be a SQLiteDatabase.")
        self._database = database

    def save_exclusive(self, confirmation: CapabilityConfirmation) -> None:
        """
        Persist a confirmation while atomically replacing any existing
        pending confirmation for the exact same security binding.

        The binding is:
        session + user + business + role + channel + integration.

        Expired pending confirmations are also revoked when replaced.
        Different bindings remain independent.
        """
        if not isinstance(confirmation, CapabilityConfirmation):
            raise TypeError(
                "confirmation must be a CapabilityConfirmation."
            )

        arguments_json = json.dumps(
            dict(confirmation.request.arguments),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )

        created_at = datetime_to_storage(confirmation.created_at)
        expires_at = datetime_to_storage(confirmation.expires_at)

        with self._database.transaction() as connection:
            connection.execute(
                """
                UPDATE capability_confirmations
                SET revoked_at = ?
                WHERE session_id_hash = ?
                  AND user_id = ?
                  AND business_id = ?
                  AND role = ?
                  AND channel IS ?
                  AND integration IS ?
                  AND consumed_at IS NULL
                  AND revoked_at IS NULL
                """,
                (
                    created_at,
                    confirmation.session_id_hash,
                    confirmation.user_id,
                    confirmation.business_id,
                    confirmation.role.value,
                    confirmation.request.channel,
                    confirmation.request.integration,
                ),
            )

            connection.execute(
                """
                INSERT INTO capability_confirmations (
                    confirmation_id,
                    session_id_hash,
                    user_id,
                    business_id,
                    role,
                    capability,
                    operation,
                    arguments_json,
                    reason,
                    channel,
                    integration,
                    created_at,
                    expires_at,
                    consumed_at,
                    revoked_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    confirmation.confirmation_id,
                    confirmation.session_id_hash,
                    confirmation.user_id,
                    confirmation.business_id,
                    confirmation.role.value,
                    confirmation.request.capability.value,
                    confirmation.request.operation,
                    arguments_json,
                    confirmation.request.reason,
                    confirmation.request.channel,
                    confirmation.request.integration,
                    created_at,
                    expires_at,
                    (
                        datetime_to_storage(confirmation.consumed_at)
                        if confirmation.consumed_at is not None
                        else None
                    ),
                    (
                        datetime_to_storage(confirmation.revoked_at)
                        if confirmation.revoked_at is not None
                        else None
                    ),
                ),
            )

    def save(self, confirmation: CapabilityConfirmation) -> None:
        if not isinstance(confirmation, CapabilityConfirmation):
            raise TypeError(
                "confirmation must be a CapabilityConfirmation."
            )

        arguments_json = json.dumps(
            dict(confirmation.request.arguments),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )

        with self._database.connection() as connection:
            connection.execute(
                """
                INSERT INTO capability_confirmations (
                    confirmation_id,
                    session_id_hash,
                    user_id,
                    business_id,
                    role,
                    capability,
                    operation,
                    arguments_json,
                    reason,
                    channel,
                    integration,
                    created_at,
                    expires_at,
                    consumed_at,
                    revoked_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    confirmation.confirmation_id,
                    confirmation.session_id_hash,
                    confirmation.user_id,
                    confirmation.business_id,
                    confirmation.role.value,
                    confirmation.request.capability.value,
                    confirmation.request.operation,
                    arguments_json,
                    confirmation.request.reason,
                    confirmation.request.channel,
                    confirmation.request.integration,
                    datetime_to_storage(confirmation.created_at),
                    datetime_to_storage(confirmation.expires_at),
                    (
                        datetime_to_storage(confirmation.consumed_at)
                        if confirmation.consumed_at is not None
                        else None
                    ),
                    (
                        datetime_to_storage(confirmation.revoked_at)
                        if confirmation.revoked_at is not None
                        else None
                    ),
                ),
            )

    def get(
        self,
        confirmation_id: str,
    ) -> CapabilityConfirmation | None:
        if not isinstance(confirmation_id, str) or not confirmation_id.strip():
            raise ValueError(
                "confirmation_id must be a non-empty string."
            )

        with self._database.connection() as connection:
            row = connection.execute(
                """
                SELECT
                    confirmation_id,
                    session_id_hash,
                    user_id,
                    business_id,
                    role,
                    capability,
                    operation,
                    arguments_json,
                    reason,
                    channel,
                    integration,
                    created_at,
                    expires_at,
                    consumed_at,
                    revoked_at
                FROM capability_confirmations
                WHERE confirmation_id = ?
                """,
                (confirmation_id,),
            ).fetchone()

        if row is None:
            return None

        return self._from_row(row)

    def consume(
        self,
        confirmation_id: str,
        *,
        session_id_hash: str,
        user_id: str,
        business_id: str,
        role: UserRole,
        channel: str | None,
        integration: str | None,
        now: datetime,
    ) -> CapabilityConfirmation | None:
        self._validate_security_binding(
            confirmation_id=confirmation_id,
            session_id_hash=session_id_hash,
            user_id=user_id,
            business_id=business_id,
            role=role,
            channel=channel,
            integration=integration,
            now=now,
        )

        now_storage = datetime_to_storage(now)

        with self._database.transaction() as connection:
            row = connection.execute(
                """
                SELECT
                    confirmation_id,
                    session_id_hash,
                    user_id,
                    business_id,
                    role,
                    capability,
                    operation,
                    arguments_json,
                    reason,
                    channel,
                    integration,
                    created_at,
                    expires_at,
                    consumed_at,
                    revoked_at
                FROM capability_confirmations
                WHERE confirmation_id = ?
                  AND session_id_hash = ?
                  AND user_id = ?
                  AND business_id = ?
                  AND role = ?
                  AND channel IS ?
                  AND integration IS ?
                  AND consumed_at IS NULL
                  AND revoked_at IS NULL
                  AND expires_at > ?
                """,
                (
                    confirmation_id,
                    session_id_hash,
                    user_id,
                    business_id,
                    role.value,
                    channel,
                    integration,
                    now_storage,
                ),
            ).fetchone()

            if row is None:
                return None

            updated = connection.execute(
                """
                UPDATE capability_confirmations
                SET consumed_at = ?
                WHERE confirmation_id = ?
                  AND session_id_hash = ?
                  AND user_id = ?
                  AND business_id = ?
                  AND role = ?
                  AND channel IS ?
                  AND integration IS ?
                  AND consumed_at IS NULL
                  AND revoked_at IS NULL
                  AND expires_at > ?
                """,
                (
                    now_storage,
                    confirmation_id,
                    session_id_hash,
                    user_id,
                    business_id,
                    role.value,
                    channel,
                    integration,
                    now_storage,
                ),
            )

            if updated.rowcount != 1:
                raise RuntimeError(
                    "Capability confirmation consumption lost its "
                    "atomic transition."
                )

            return self._from_row(
                connection.execute(
                    """
                    SELECT
                        confirmation_id,
                        session_id_hash,
                        user_id,
                        business_id,
                        role,
                        capability,
                        operation,
                        arguments_json,
                        reason,
                        channel,
                        integration,
                        created_at,
                        expires_at,
                        consumed_at,
                        revoked_at
                    FROM capability_confirmations
                    WHERE confirmation_id = ?
                    """,
                    (confirmation_id,),
                ).fetchone()
            )

    def revoke(
        self,
        confirmation_id: str,
        *,
        session_id_hash: str,
        user_id: str,
        business_id: str,
        role: UserRole,
        channel: str | None,
        integration: str | None,
        now: datetime,
    ) -> bool:
        self._validate_security_binding(
            confirmation_id=confirmation_id,
            session_id_hash=session_id_hash,
            user_id=user_id,
            business_id=business_id,
            role=role,
            channel=channel,
            integration=integration,
            now=now,
        )

        with self._database.transaction() as connection:
            result = connection.execute(
                """
                UPDATE capability_confirmations
                SET revoked_at = ?
                WHERE confirmation_id = ?
                  AND session_id_hash = ?
                  AND user_id = ?
                  AND business_id = ?
                  AND role = ?
                  AND channel IS ?
                  AND integration IS ?
                  AND consumed_at IS NULL
                  AND revoked_at IS NULL
                """,
                (
                    datetime_to_storage(now),
                    confirmation_id,
                    session_id_hash,
                    user_id,
                    business_id,
                    role.value,
                    channel,
                    integration,
                ),
            )

            return result.rowcount == 1

    @staticmethod
    def _validate_security_binding(
        *,
        confirmation_id: str,
        session_id_hash: str,
        user_id: str,
        business_id: str,
        role: UserRole,
        channel: str | None,
        integration: str | None,
        now: datetime,
    ) -> None:
        if not isinstance(confirmation_id, str) or not confirmation_id.strip():
            raise ValueError(
                "confirmation_id must be a non-empty string."
            )

        for name, value in (
            ("session_id_hash", session_id_hash),
            ("user_id", user_id),
            ("business_id", business_id),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"{name} must be a non-empty string."
                )

        if not isinstance(role, UserRole):
            raise TypeError("role must be a UserRole.")

        for name, value in (
            ("channel", channel),
            ("integration", integration),
        ):
            if value is not None and (
                not isinstance(value, str) or not value.strip()
            ):
                raise ValueError(
                    f"{name} must be a non-empty string when provided."
                )

        datetime_to_storage(now)

    @staticmethod
    def _from_row(row: sqlite3.Row) -> CapabilityConfirmation:
        try:
            capability = Capability(row["capability"])
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                "Stored capability confirmation contains an invalid "
                "capability."
            ) from exc

        try:
            role = UserRole(row["role"])
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                "Stored capability confirmation contains an invalid role."
            ) from exc

        try:
            arguments = json.loads(row["arguments_json"])
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                "Stored capability confirmation contains invalid "
                "arguments JSON."
            ) from exc

        if not isinstance(arguments, dict):
            raise RuntimeError(
                "Stored capability confirmation arguments must be an object."
            )

        request = CapabilityExecutionRequest(
            capability=capability,
            operation=row["operation"],
            business_id=row["business_id"],
            arguments=arguments,
            reason=row["reason"],
            channel=row["channel"],
            integration=row["integration"],
        )

        return CapabilityConfirmation(
            confirmation_id=row["confirmation_id"],
            session_id_hash=row["session_id_hash"],
            user_id=row["user_id"],
            business_id=row["business_id"],
            role=role,
            request=request,
            created_at=datetime_from_storage(row["created_at"]),
            expires_at=datetime_from_storage(row["expires_at"]),
            consumed_at=(
                datetime_from_storage(row["consumed_at"])
                if row["consumed_at"] is not None
                else None
            ),
            revoked_at=(
                datetime_from_storage(row["revoked_at"])
                if row["revoked_at"] is not None
                else None
            ),
        )
