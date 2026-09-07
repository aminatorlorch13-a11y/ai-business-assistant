from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Mapping


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {
                key: _freeze(item)
                for key, item in value.items()
            }
        )

    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)

    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)

    if isinstance(value, set):
        return frozenset(_freeze(item) for item in value)

    return value


@dataclass(frozen=True)
class PaymentProviderEvent:
    """
    Immutable, provider-neutral representation of received provider data.

    This object represents RECEIVED provider data.

    It is not proof that:
    - the event is authentic,
    - the payment succeeded,
    - the amount is correct,
    - the business is entitled to service,
    - or the payment should activate a business.

    Authenticity belongs to the provider adapter.
    Semantic payment verification belongs to PaymentVerifier.
    """

    provider: str
    event_id: str
    event_type: str
    payload: Mapping[str, object]
    received_at: datetime

    def __post_init__(self) -> None:
        self._validate_non_empty_string("provider", self.provider)
        self._validate_non_empty_string("event_id", self.event_id)
        self._validate_non_empty_string("event_type", self.event_type)

        if not isinstance(self.payload, Mapping):
            raise TypeError("payload must be a mapping.")

        if not self.payload:
            raise ValueError("payload must not be empty.")

        frozen_payload = _freeze(self.payload)

        if not isinstance(frozen_payload, Mapping):
            raise TypeError("payload could not be frozen.")

        object.__setattr__(self, "payload", frozen_payload)

        if not isinstance(self.received_at, datetime):
            raise TypeError("received_at must be a datetime.")

        if self.received_at.tzinfo is None:
            raise ValueError("received_at must be timezone-aware.")

        if self.received_at.utcoffset() is None:
            raise ValueError("received_at must have a valid UTC offset.")

    @staticmethod
    def _validate_non_empty_string(field_name: str, value: object) -> None:
        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be a string.")

        if not value.strip():
            raise ValueError(f"{field_name} must be a non-empty string.")
