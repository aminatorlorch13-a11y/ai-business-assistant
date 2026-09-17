from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.persistence.platform_event_repository import SQLitePlatformEventRepository
from app.platform.events import (
    PlatformEvent,
    PlatformEventActorType,
    PlatformEventChannel,
    PlatformEventOutcome,
)


class PlatformEventExecutionTelemetry:
    """Execution telemetry backed by the append-only platform event store."""

    _EVENT_TYPE = "assistant.execution"

    def __init__(self, repository: SQLitePlatformEventRepository) -> None:
        if not isinstance(repository, SQLitePlatformEventRepository):
            raise TypeError(
                "repository must be a SQLitePlatformEventRepository."
            )
        self._repository = repository

    def record(
        self,
        *,
        business_id: str,
        user_id: str | None,
        action_type: str,
        outcome: PlatformEventOutcome,
        channel: str | None,
        integration: str | None,
        reason: str | None = None,
    ) -> None:
        if channel is None:
            return

        try:
            event_channel = PlatformEventChannel(channel)
        except ValueError as exc:
            raise ValueError(
                f"Unsupported execution telemetry channel: {channel!r}."
            ) from exc

        metadata: dict[str, str] = {
            "action_type": action_type,
        }

        if integration is not None:
            metadata["integration"] = integration

        if reason is not None:
            metadata["reason"] = reason

        event = PlatformEvent(
            event_id=f"event-{uuid4().hex}",
            occurred_at=datetime.now(timezone.utc),
            event_type=self._EVENT_TYPE,
            business_id=business_id,
            user_id=user_id,
            channel=event_channel,
            actor_type=PlatformEventActorType.USER,
            action=action_type,
            outcome=outcome,
            correlation_id=f"execution-{uuid4().hex}",
            metadata=metadata,
        )

        self._repository.append(event)
