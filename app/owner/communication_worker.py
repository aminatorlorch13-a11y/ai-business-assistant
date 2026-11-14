from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import threading
import uuid

from app.whatsapp.provider import (
    WhatsAppProviderError,
    WhatsAppProviderOutcomeUnknown,
)

logger = logging.getLogger(__name__)


class CommunicationDeliveryWorker:
    """Background executor for tenant-scoped communication deliveries."""

    def __init__(
        self,
        repository,
        communication_service,
        provider,
        *,
        worker_id=None,
        poll_seconds=3,
        lease_seconds=60,
        batch_size=10,
        base_retry_seconds=30,
        max_retry_seconds=1800,
    ):
        if repository is None or communication_service is None:
            raise ValueError("Communication persistence and service are required.")
        if provider is None:
            raise ValueError("A real WhatsApp provider is required.")
        if not 1 <= poll_seconds <= 300:
            raise ValueError("Invalid polling interval.")
        if not 5 <= lease_seconds <= 900:
            raise ValueError("Invalid lease duration.")
        if not 1 <= batch_size <= 100:
            raise ValueError("Invalid batch size.")

        self.repository = repository
        self.service = communication_service
        self.provider = provider
        self.worker_id = worker_id or f"communication-{uuid.uuid4()}"
        self.poll_seconds = poll_seconds
        self.lease_seconds = lease_seconds
        self.batch_size = batch_size
        self.base_retry_seconds = base_retry_seconds
        self.max_retry_seconds = max_retry_seconds
        self._stop_event = threading.Event()
        self._thread = None

    @staticmethod
    def _message(event):
        parts = [str(event["title"]).strip()]
        details = event.get("details")
        if details and str(details).strip():
            parts.append(str(details).strip())
        return "\n\n".join(parts)[:4096]

    def _retry_at(self, attempts):
        delay = min(
            self.base_retry_seconds * (2 ** max(0, attempts - 1)),
            self.max_retry_seconds,
        )
        return (
            datetime.now(timezone.utc) + timedelta(seconds=delay)
        ).isoformat()

    def _tenant_scopes(self):
        now = datetime.now(timezone.utc).isoformat()
        with self.repository.database.connection() as db:
            rows = db.execute("""
                SELECT DISTINCT business_id, user_id
                FROM attention_delivery_attempts
                WHERE (
                    status = 'queued'
                    AND next_attempt_at <= ?
                    AND attempts < max_attempts
                ) OR (
                    status = 'claimed'
                    AND lease_expires_at <= ?
                )
                ORDER BY business_id, user_id
            """, (now, now)).fetchall()
        return [(row["business_id"], row["user_id"]) for row in rows]

    def _delivery_context(self, attempt):
        with self.repository.database.connection() as db:
            row = db.execute("""
                SELECT
                    d.delivery_id,
                    d.event_id,
                    d.business_id,
                    d.user_id,
                    d.endpoint_id,
                    d.channel,
                    d.claim_token,
                    d.attempts,
                    e.title,
                    e.details,
                    c.encrypted_endpoint,
                    c.key_version AS endpoint_key_version,
                    i.provider AS identity_provider,
                    i.encrypted_identity,
                    i.key_version AS identity_key_version,
                    i.status AS identity_status
                FROM attention_delivery_attempts d
                JOIN attention_events e
                  ON e.event_id = d.event_id
                 AND e.business_id = d.business_id
                 AND e.user_id = d.user_id
                JOIN owner_communication_channels c
                  ON c.endpoint_id = d.endpoint_id
                 AND c.business_id = d.business_id
                 AND c.user_id = d.user_id
                LEFT JOIN tenant_communication_identities i
                  ON i.business_id = d.business_id
                WHERE d.delivery_id = ?
                  AND d.status = 'claimed'
                  AND d.claim_token = ?
                  AND c.revoked_at IS NULL
                  AND c.verified_at IS NOT NULL
                  AND c.consent_granted_at IS NOT NULL
            """, (attempt["delivery_id"], attempt["claim_token"])).fetchone()

        return dict(row) if row else None

    def _finish(self, attempt, outcome, **kwargs):
        return self.repository.finish_attempt(
            delivery_id=attempt["delivery_id"],
            claim_token=attempt["claim_token"],
            outcome=outcome,
            **kwargs,
        )

    def _execute(self, attempt):
        send_started = False

        try:
            context = self._delivery_context(attempt)

            if context is None:
                self._finish(
                    attempt,
                    "failed",
                    failure_reason="delivery_context_unavailable_or_revoked",
                )
                return "failed"

            if context["channel"] != "whatsapp":
                self._finish(
                    attempt,
                    "failed",
                    failure_reason=f"no_configured_adapter_for_{context['channel']}",
                )
                return "failed"

            if (
                context["identity_status"] != "active"
                or not context["encrypted_identity"]
                or "whatsapp" not in str(context["identity_provider"]).casefold()
            ):
                self._finish(
                    attempt,
                    "failed",
                    failure_reason="verified_active_whatsapp_provider_identity_required",
                )
                return "failed"

            # Preparation happens before the external send. Failures here
            # are definite preparation failures, not ambiguous sends.
            endpoint = self.service._decrypt(
                context["encrypted_endpoint"],
                context["endpoint_key_version"],
            )
            provider_account_id = self.service._decrypt(
                context["encrypted_identity"],
                context["identity_key_version"],
            )
            message = self._message(context)

            send_started = True
            message_id = self.provider.send_text(
                provider_account_id=provider_account_id,
                recipient=endpoint,
                text=message,
            )

            if not isinstance(message_id, str) or not message_id.strip():
                raise WhatsAppProviderOutcomeUnknown(
                    "Provider returned no confirmed message ID."
                )

            if not self._finish(
                attempt,
                "sent",
                provider_reference=message_id,
            ):
                return "claim_lost"

            return "sent"

        except WhatsAppProviderOutcomeUnknown as exc:
            self._finish(
                attempt,
                "unknown",
                failure_reason=f"provider_outcome_unknown:{str(exc)[:400]}",
            )
            return "unknown"

        except WhatsAppProviderError as exc:
            retry_at = (
                self._retry_at(attempt["attempts"])
                if attempt["attempts"] < attempt["max_attempts"]
                else None
            )
            self._finish(
                attempt,
                "failed",
                failure_reason=f"provider_rejected:{str(exc)[:400]}",
                retry_at=retry_at,
            )
            return "retry" if retry_at else "failed"

        except Exception as exc:
            if send_started:
                outcome = "unknown"
                reason = "unexpected_provider_outcome_unknown"
            else:
                outcome = "failed"
                reason = f"delivery_preparation_failed:{str(exc)[:350]}"

            try:
                self._finish(
                    attempt,
                    outcome,
                    failure_reason=reason,
                )
            except Exception:
                logger.exception(
                    "Could not persist communication delivery outcome."
                )

            logger.exception("Communication delivery execution failed.")
            return outcome

    def run_once(self):
        totals = {
            "claimed": 0,
            "sent": 0,
            "retry": 0,
            "failed": 0,
            "unknown": 0,
            "claim_lost": 0,
        }

        for business_id, user_id in self._tenant_scopes():
            self.repository.recover_expired_claims(
                business_id=business_id,
                user_id=user_id,
                limit=100,
            )

            attempts = self.repository.claim_due_attempts(
                business_id=business_id,
                user_id=user_id,
                worker_id=self.worker_id,
                limit=self.batch_size,
                lease_seconds=self.lease_seconds,
            )
            totals["claimed"] += len(attempts)

            for attempt in attempts:
                result = self._execute(attempt)
                totals[result] += 1

        return totals

    def _run(self):
        logger.info("Communication delivery worker started: %s", self.worker_id)
        while not self._stop_event.is_set():
            try:
                self.run_once()
            except Exception:
                logger.exception("Communication worker cycle failed.")
            self._stop_event.wait(self.poll_seconds)
        logger.info("Communication delivery worker stopped: %s", self.worker_id)

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return False
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name=self.worker_id,
            daemon=True,
        )
        self._thread.start()
        return True

    def stop(self, timeout=10):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        return self._thread is None or not self._thread.is_alive()
