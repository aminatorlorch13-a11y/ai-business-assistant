from __future__ import annotations

import json
from datetime import datetime

from app.persistence.database import SQLiteDatabase
from app.persistence.serialization import datetime_from_storage
from app.platform.events import (
    PlatformEvent,
    PlatformEventActorType,
    PlatformEventChannel,
    PlatformEventOutcome,
)


class SQLitePlatformEventRepository:
    """Durable append-only repository for platform evidence events."""

    MAX_ID_LENGTH = PlatformEvent.MAX_ID_LENGTH
    MAX_LIST_LIMIT = 500

    def __init__(self, database: SQLiteDatabase) -> None:
        if not isinstance(database, SQLiteDatabase):
            raise TypeError("database must be a SQLiteDatabase.")
        self._database = database

    def append(self, event: PlatformEvent) -> PlatformEvent:
        if not isinstance(event, PlatformEvent):
            raise TypeError("event must be a PlatformEvent.")

        metadata_json = json.dumps(
            event.metadata,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

        with self._database.transaction() as connection:
            if event.business_id is not None:
                row = connection.execute(
                    """
                    SELECT 1
                    FROM businesses
                    WHERE business_id = ?
                    """,
                    (event.business_id,),
                ).fetchone()

                if row is None:
                    raise ValueError(
                        "business_id does not reference an existing business."
                    )

            if event.user_id is not None:
                row = connection.execute(
                    """
                    SELECT 1
                    FROM users
                    WHERE user_id = ?
                    """,
                    (event.user_id,),
                ).fetchone()

                if row is None:
                    raise ValueError(
                        "user_id does not reference an existing user."
                    )

            try:
                connection.execute(
                    """
                    INSERT INTO platform_events(
                        event_id,
                        occurred_at,
                        event_type,
                        business_id,
                        user_id,
                        channel,
                        actor_type,
                        action,
                        outcome,
                        correlation_id,
                        metadata
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.storage_occurred_at(),
                        event.event_type,
                        event.business_id,
                        event.user_id,
                        event.channel.value,
                        event.actor_type.value,
                        event.action,
                        event.outcome.value,
                        event.correlation_id,
                        metadata_json,
                    ),
                )
            except Exception as exc:
                if "UNIQUE constraint failed" in str(exc):
                    raise ValueError(
                        "A platform event with this event_id already exists."
                    ) from exc
                raise

        return event

    def get(self, event_id: str) -> PlatformEvent | None:
        self._validate_id(event_id)

        with self._database.connection() as connection:
            row = connection.execute(
                """
                SELECT
                    event_id,
                    occurred_at,
                    event_type,
                    business_id,
                    user_id,
                    channel,
                    actor_type,
                    action,
                    outcome,
                    correlation_id,
                    metadata
                FROM platform_events
                WHERE event_id = ?
                """,
                (event_id,),
            ).fetchone()

        return self._row_to_event(row) if row else None

    def list_for_business(
        self,
        business_id: str,
        *,
        limit: int = 100,
    ) -> list[PlatformEvent]:
        self._validate_id(business_id)
        self._validate_limit(limit)

        with self._database.connection() as connection:
            rows = connection.execute(
                """
                SELECT
                    event_id,
                    occurred_at,
                    event_type,
                    business_id,
                    user_id,
                    channel,
                    actor_type,
                    action,
                    outcome,
                    correlation_id,
                    metadata
                FROM platform_events
                WHERE business_id = ?
                ORDER BY occurred_at DESC, event_id DESC
                LIMIT ?
                """,
                (business_id, limit),
            ).fetchall()

        return [self._row_to_event(row) for row in rows]

    def list_for_correlation(
        self,
        correlation_id: str,
        *,
        limit: int = 100,
    ) -> list[PlatformEvent]:
        self._validate_id(correlation_id)
        self._validate_limit(limit)

        with self._database.connection() as connection:
            rows = connection.execute(
                """
                SELECT
                    event_id,
                    occurred_at,
                    event_type,
                    business_id,
                    user_id,
                    channel,
                    actor_type,
                    action,
                    outcome,
                    correlation_id,
                    metadata
                FROM platform_events
                WHERE correlation_id = ?
                ORDER BY occurred_at DESC, event_id DESC
                LIMIT ?
                """,
                (correlation_id, limit),
            ).fetchall()

        return [self._row_to_event(row) for row in rows]

    def list_recent(
        self,
        *,
        limit: int = 100,
    ) -> list[PlatformEvent]:
        self._validate_limit(limit)

        with self._database.connection() as connection:
            rows = connection.execute(
                """
                SELECT
                    event_id,
                    occurred_at,
                    event_type,
                    business_id,
                    user_id,
                    channel,
                    actor_type,
                    action,
                    outcome,
                    correlation_id,
                    metadata
                FROM platform_events
                ORDER BY occurred_at DESC, event_id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return [self._row_to_event(row) for row in rows]

    @staticmethod
    def _row_to_event(row: object) -> PlatformEvent:
        metadata = json.loads(row["metadata"])

        return PlatformEvent(
            event_id=row["event_id"],
            occurred_at=datetime_from_storage(row["occurred_at"]),
            event_type=row["event_type"],
            business_id=row["business_id"],
            user_id=row["user_id"],
            channel=PlatformEventChannel(row["channel"]),
            actor_type=PlatformEventActorType(row["actor_type"]),
            action=row["action"],
            outcome=PlatformEventOutcome(row["outcome"]),
            correlation_id=row["correlation_id"],
            metadata=metadata,
        )

    @classmethod
    def _validate_id(cls, value: object) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("identifier must be a non-empty string.")

        if len(value) > cls.MAX_ID_LENGTH:
            raise ValueError(
                "identifier exceeds the maximum allowed length."
            )

    @classmethod
    def _validate_limit(cls, value: int) -> None:
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError("limit must be an integer.")

        if value < 1 or value > cls.MAX_LIST_LIMIT:
            raise ValueError(
                f"limit must be between 1 and {cls.MAX_LIST_LIMIT}."
            )
