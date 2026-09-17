from collections.abc import Mapping
from dataclasses import dataclass

from app.automation.event import AutomationEvent, _freeze_value


@dataclass(frozen=True)
class AutomationContext:
    """Trusted, immutable context derived from an automation event."""

    business_id: str
    event_type: str
    payload: Mapping[str, object]

    @classmethod
    def from_event(
        cls,
        event: AutomationEvent,
    ) -> "AutomationContext":
        """Create trusted automation context from a validated event."""

        if not isinstance(event, AutomationEvent):
            raise TypeError("event must be an AutomationEvent.")

        return cls(
            business_id=event.business_id,
            event_type=event.event_type,
            payload=event.payload,
        )

    def __post_init__(self) -> None:
        if not isinstance(self.business_id, str):
            raise TypeError("business_id must be a string.")

        if not self.business_id.strip():
            raise ValueError(
                "business_id must be a non-empty string."
            )

        if not isinstance(self.event_type, str):
            raise TypeError("event_type must be a string.")

        if not self.event_type.strip():
            raise ValueError(
                "event_type must be a non-empty string."
            )

        if not isinstance(self.payload, Mapping):
            raise TypeError("payload must be a mapping.")

        frozen_payload = _freeze_value(self.payload)

        if not isinstance(frozen_payload, Mapping):
            raise TypeError("payload must be a mapping.")

        object.__setattr__(
            self,
            "payload",
            frozen_payload,
        )
