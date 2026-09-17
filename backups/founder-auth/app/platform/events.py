from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Mapping

from app.persistence.serialization import datetime_to_storage


class PlatformEventChannel(str, Enum):
    SYSTEM = "system"
    WEB = "web"
    WHATSAPP = "whatsapp"
    VOICE = "voice"
    API = "api"
    FOUNDER = "founder"


class PlatformEventActorType(str, Enum):
    USER = "user"
    FOUNDER = "founder"
    SYSTEM = "system"
    PROVIDER = "provider"


class PlatformEventOutcome(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    DENIED = "denied"
    ERROR = "error"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class PlatformEvent:
    event_id: str
    occurred_at: datetime
    event_type: str
    business_id: str | None
    user_id: str | None
    channel: PlatformEventChannel
    actor_type: PlatformEventActorType
    action: str
    outcome: PlatformEventOutcome
    correlation_id: str
    metadata: Mapping[str, Any]

    MAX_ID_LENGTH = 128
    MAX_EVENT_TYPE_LENGTH = 128
    MAX_ACTION_LENGTH = 128
    MAX_METADATA_BYTES = 16_384
    MAX_METADATA_DEPTH = 5
    MAX_METADATA_KEYS = 64
    MAX_METADATA_ITEMS = 64
    MAX_METADATA_STRING_LENGTH = 2_048

    _FORBIDDEN_METADATA_TERMS = frozenset(
        {
            "password",
            "passwd",
            "secret",
            "token",
            "api_key",
            "apikey",
            "access_token",
            "refresh_token",
            "authorization",
            "cookie",
            "credential",
            "private_key",
        }
    )

    def __post_init__(self) -> None:
        self._validate_id("event_id", self.event_id)
        self._validate_id("correlation_id", self.correlation_id)

        if self.business_id is not None:
            self._validate_id("business_id", self.business_id)

        if self.user_id is not None:
            self._validate_id("user_id", self.user_id)

        if not isinstance(self.occurred_at, datetime):
            raise TypeError("occurred_at must be a datetime.")

        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware.")

        if not isinstance(self.event_type, str) or not self.event_type.strip():
            raise ValueError("event_type must be a non-empty string.")

        if len(self.event_type) > self.MAX_EVENT_TYPE_LENGTH:
            raise ValueError("event_type exceeds the maximum allowed length.")

        if not isinstance(self.action, str) or not self.action.strip():
            raise ValueError("action must be a non-empty string.")

        if len(self.action) > self.MAX_ACTION_LENGTH:
            raise ValueError("action exceeds the maximum allowed length.")

        if not isinstance(self.channel, PlatformEventChannel):
            raise TypeError("channel must be a PlatformEventChannel.")

        if not isinstance(self.actor_type, PlatformEventActorType):
            raise TypeError("actor_type must be a PlatformEventActorType.")

        if not isinstance(self.outcome, PlatformEventOutcome):
            raise TypeError("outcome must be a PlatformEventOutcome.")

        sanitized = self._sanitize_metadata(self.metadata)

        object.__setattr__(self, "metadata", sanitized)

    def storage_occurred_at(self) -> str:
        return datetime_to_storage(self.occurred_at)

    @classmethod
    def _validate_id(cls, name: str, value: object) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string.")

        if len(value) > cls.MAX_ID_LENGTH:
            raise ValueError(
                f"{name} exceeds the maximum allowed length."
            )

    @classmethod
    def _sanitize_metadata(
        cls,
        value: Mapping[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise TypeError("metadata must be a mapping.")

        result = cls._sanitize_mapping(value, depth=0)

        encoded = json.dumps(
            result,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

        if len(encoded.encode("utf-8")) > cls.MAX_METADATA_BYTES:
            raise ValueError(
                "metadata exceeds the maximum allowed serialized size."
            )

        return result

    @classmethod
    def _sanitize_mapping(
        cls,
        value: Mapping[str, Any],
        *,
        depth: int,
    ) -> dict[str, Any]:
        if depth > cls.MAX_METADATA_DEPTH:
            raise ValueError("metadata nesting depth is too large.")

        if len(value) > cls.MAX_METADATA_KEYS:
            raise ValueError("metadata contains too many keys.")

        result: dict[str, Any] = {}

        for raw_key, raw_value in value.items():
            if not isinstance(raw_key, str) or not raw_key.strip():
                raise ValueError("metadata keys must be non-empty strings.")

            if len(raw_key) > 128:
                raise ValueError("metadata key is too long.")

            normalized_key = raw_key.strip().lower()

            if any(
                term == normalized_key
                or term in normalized_key
                for term in cls._FORBIDDEN_METADATA_TERMS
            ):
                raise ValueError(
                    f"metadata key '{raw_key}' is not permitted."
                )

            result[raw_key] = cls._sanitize_value(
                raw_value,
                depth=depth + 1,
            )

        return result

    @classmethod
    def _sanitize_value(
        cls,
        value: Any,
        *,
        depth: int,
    ) -> Any:
        if value is None or isinstance(value, (bool, int, float)):
            return value

        if isinstance(value, str):
            if len(value) > cls.MAX_METADATA_STRING_LENGTH:
                raise ValueError(
                    "metadata string value is too long."
                )
            return value

        if isinstance(value, Mapping):
            return cls._sanitize_mapping(value, depth=depth)

        if isinstance(value, (list, tuple)):
            if len(value) > cls.MAX_METADATA_ITEMS:
                raise ValueError(
                    "metadata list contains too many items."
                )

            return [
                cls._sanitize_value(item, depth=depth)
                for item in value
            ]

        raise TypeError(
            "metadata may only contain JSON-compatible primitive, "
            "mapping, list, or null values."
        )
