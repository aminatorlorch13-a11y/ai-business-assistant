from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any


SUPPORTED_EVENT_TYPES = frozenset(
    {
        "email_received",
        "form_submitted",
        "order_received",
        "appointment_created",
        "reminder_due",
    }
)


def _freeze_value(value: Any) -> Any:
    """Recursively convert mutable container values into immutable values."""
    if isinstance(value, Mapping):
        frozen_items = {
            key: _freeze_value(item)
            for key, item in value.items()
        }
        return MappingProxyType(frozen_items)

    if isinstance(value, list):
        return tuple(_freeze_value(item) for item in value)

    if isinstance(value, tuple):
        return tuple(_freeze_value(item) for item in value)

    if isinstance(value, set):
        return frozenset(_freeze_value(item) for item in value)

    if isinstance(value, frozenset):
        return frozenset(_freeze_value(item) for item in value)

    return value


@dataclass(frozen=True)
class AutomationEvent:
    """Immutable event entering the business automation engine."""

    business_id: str
    event_type: str
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        if not isinstance(self.business_id, str):
            raise TypeError("business_id must be a string.")

        if not self.business_id.strip():
            raise ValueError("business_id must be a non-empty string.")

        if not isinstance(self.event_type, str):
            raise TypeError("event_type must be a string.")

        if not self.event_type.strip():
            raise ValueError("event_type must be a non-empty string.")

        if self.event_type not in SUPPORTED_EVENT_TYPES:
            raise ValueError(
                "event_type must be one of: "
                f"{', '.join(sorted(SUPPORTED_EVENT_TYPES))}."
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
