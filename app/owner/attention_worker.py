from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import uuid

from app.whatsapp.provider import (
    WhatsAppProviderError,
    WhatsAppProviderOutcomeUnknown,
)


@dataclass(frozen=True, slots=True)
class AttentionDeliveryTarget:
    """Explicitly configured owner WhatsApp delivery destination."""

    business_id: str
    user_id: str
    provider_account_id: str
    recipient: str

    def __post_init__(self):
        for name in (
            "business_id",
            "user_id",
            "provider_account_id",
            "recipient",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} is required.")


@dataclass(frozen=True, slots=True)
class AttentionWorkerResult:
    claimed: int
    delivered: int
    retry_scheduled: int
    failed: int
    claim_lost: int


class AttentionWorker:
    """Delivers explicitly authorized owner attention events."""

    DIRECT_ACTIONS = ("interrupt", "deliver")

    def __init__(
        self,
        event_repository,
        provider,
        target,
        *,
        worker_id=None,
        lease_seconds=60,
        max_attempts=5,
        base_retry_seconds=60,
        max_retry_seconds=3600,
    ):
        if target is None or not isinstance(target, AttentionDeliveryTarget):
            raise ValueError("An explicit delivery target is required.")

        if provider is None:
            raise ValueError("A configured WhatsApp provider is required.")

        if type(lease_seconds) is not int or not 1 <= lease_seconds <= 3600:
            raise ValueError("Invalid lease duration.")

        if type(max_attempts) is not int or max_attempts < 1:
            raise ValueError("max_attempts must be positive.")

        if type(base_retry_seconds) is not int or base_retry_seconds < 1:
            raise ValueError("Invalid base retry interval.")

        if type(max_retry_seconds) is not int or max_retry_seconds < base_retry_seconds:
            raise ValueError("Invalid maximum retry interval.")

        self.events = event_repository
        self.provider = provider
        self.target = target
        self.worker_id = worker_id or f"attention-{uuid.uuid4()}"
        self.lease_seconds = lease_seconds
        self.max_attempts = max_attempts
        self.base_retry_seconds = base_retry_seconds
        self.max_retry_seconds = max_retry_seconds

    @staticmethod
    def _message(event):
        parts = [event.title.strip()]

        if event.details and event.details.strip():
            parts.append(event.details.strip())

        # Do not send arbitrary event payloads to the messaging channel.
        return "\n\n".join(parts)[:4096]

    def _retry_time(self, attempt_number):
        delay = min(
            self.base_retry_seconds * (2 ** max(0, attempt_number - 1)),
            self.max_retry_seconds,
        )
        return (
            datetime.now(timezone.utc) + timedelta(seconds=delay)
        ).isoformat()

    def run_once(self, *, limit=10):
        target = self.target

        events = self.events.claim_due_events(
            target.business_id,
            target.user_id,
            self.worker_id,
            limit=limit,
            lease_seconds=self.lease_seconds,
            actions=self.DIRECT_ACTIONS,
        )

        delivered = 0
        retry_scheduled = 0
        failed = 0
        claim_lost = 0

        for event in events:
            try:
                self.events.record_claim_attempt(
                    target.business_id,
                    target.user_id,
                    event.event_id,
                    event.claim_token,
                )
            except ValueError:
                claim_lost += 1
                continue

            attempt_number = event.attempts + 1

            try:
                message_id = self.provider.send_text(
                    provider_account_id=target.provider_account_id,
                    recipient=target.recipient,
                    text=self._message(event),
                )

                if not isinstance(message_id, str) or not message_id.strip():
                    raise WhatsAppProviderOutcomeUnknown(
                        "Provider returned no confirmed message ID."
                    )

                self.events.complete_claim(
                    target.business_id,
                    target.user_id,
                    event.event_id,
                    event.claim_token,
                    message_id,
                )
                delivered += 1

            except WhatsAppProviderOutcomeUnknown:
                # The provider may have accepted the message.
                # Never automatically resend an ambiguous delivery.
                self.events.fail_claim(
                    target.business_id,
                    target.user_id,
                    event.event_id,
                    event.claim_token,
                    "provider_outcome_unknown_manual_reconciliation_required",
                )
                failed += 1

            except WhatsAppProviderError as exc:
                reason = f"provider_rejected: {str(exc)[:500]}"

                if attempt_number >= self.max_attempts:
                    self.events.fail_claim(
                        target.business_id,
                        target.user_id,
                        event.event_id,
                        event.claim_token,
                        f"maximum_attempts_reached: {reason}",
                    )
                    failed += 1
                else:
                    self.events.release_claim(
                        target.business_id,
                        target.user_id,
                        event.event_id,
                        event.claim_token,
                        reason=reason,
                        retry_after=self._retry_time(attempt_number),
                    )
                    retry_scheduled += 1

            except Exception:
                # An unexpected exception after calling the provider is
                # treated as ambiguous. Retrying could duplicate a message.
                self.events.fail_claim(
                    target.business_id,
                    target.user_id,
                    event.event_id,
                    event.claim_token,
                    "unexpected_delivery_error_manual_reconciliation_required",
                )
                failed += 1

        return AttentionWorkerResult(
            claimed=len(events),
            delivered=delivered,
            retry_scheduled=retry_scheduled,
            failed=failed,
            claim_lost=claim_lost,
        )
