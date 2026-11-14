"""Authenticated event ingestion and owner attention-policy orchestration."""

import json
import re

from app.owner.attention_policy import OwnerAttentionPolicy
from app.owner.attention_events import SEVERITIES


_EVENT_TYPE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_.-]{0,99}$")


class OwnerAttentionService:
    """Evaluate and persist events within an authenticated owner boundary."""

    MAX_TITLE_LENGTH = 200
    MAX_DETAILS_LENGTH = 4000
    MAX_IDEMPOTENCY_LENGTH = 200
    MAX_PAYLOAD_BYTES = 16_384

    def __init__(
        self,
        lifestyle_service,
        event_repository,
        policy=None,
        *,
        communication_service=None,
    ):
        self.lifestyle = lifestyle_service
        self.events = event_repository
        self.policy = policy or OwnerAttentionPolicy
        self.communication_service = communication_service

    @staticmethod
    def _required_text(value, name, maximum):
        if not isinstance(value, str):
            raise TypeError(f"{name} must be text.")
        value = value.strip()
        if not value:
            raise ValueError(f"{name} is required.")
        if len(value) > maximum:
            raise ValueError(f"{name} exceeds its maximum length.")
        return value

    @classmethod
    def _validate_payload(cls, payload):
        if payload is None:
            return {}

        if not isinstance(payload, dict):
            raise TypeError("Event payload must be an object.")

        try:
            encoded = json.dumps(
                payload,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("Event payload must contain valid JSON data.") from exc

        if len(encoded.encode("utf-8")) > cls.MAX_PAYLOAD_BYTES:
            raise ValueError("Event payload exceeds the size limit.")

        return payload

    def ingest(
        self,
        principal,
        business_id,
        *,
        idempotency_key,
        event_type,
        severity,
        title,
        details="",
        payload=None,
        now=None,
    ):
        """Evaluate and persist one event for an authenticated owner."""

        # This verifies the authenticated user and business membership.
        user_id = self.lifestyle.identity(principal, business_id)

        idempotency_key = self._required_text(
            idempotency_key, "Idempotency key",
            self.MAX_IDEMPOTENCY_LENGTH,
        )
        event_type = self._required_text(
            event_type, "Event type", 100,
        )
        if not _EVENT_TYPE.fullmatch(event_type):
            raise ValueError("Invalid event type format.")

        title = self._required_text(
            title, "Event title", self.MAX_TITLE_LENGTH,
        )

        if not isinstance(details, str):
            raise TypeError("Event details must be text.")
        if len(details) > self.MAX_DETAILS_LENGTH:
            raise ValueError("Event details exceed the size limit.")

        if severity not in SEVERITIES:
            raise ValueError("Invalid event severity.")

        payload = self._validate_payload(payload)

        preferences = self.lifestyle.get_preferences(
            principal, business_id,
        )

        decision = self.policy.evaluate(
            preferences,
            severity,
            now=now,
        )

        event = self.events.create(
            business_id,
            user_id,
            idempotency_key=idempotency_key,
            event_type=event_type,
            severity=severity,
            title=title,
            details=details,
            payload=payload,
            decision=decision,
        )

        # Queue immediate events through the consent-checked communication
        # service. Repeated ingestion remains safe through event idempotency.
        if (
            self.communication_service is not None
            and event.action in {"interrupt", "deliver"}
        ):
            self.communication_service.queue_event_delivery(
                principal,
                business_id,
                event_id=event.event_id,
            )

        return event
