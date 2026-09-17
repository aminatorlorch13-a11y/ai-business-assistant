from __future__ import annotations

from typing import Protocol

from app.platform.events import PlatformEventOutcome


class ExecutionTelemetry(Protocol):
    """Records authoritative assistant execution outcomes."""

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
        """Record one execution outcome."""
        ...
