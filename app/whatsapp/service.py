from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from app.assistant.conversation import ConversationHistory
from app.assistant.message import AssistantMessage
from app.assistant.orchestrator import AssistantOrchestrator
from app.delivery.state import DeliveryState
from app.identity.tenant import TenantContext
from app.persistence.whatsapp import (
    SQLiteWhatsAppRepository,
    WhatsAppMessageRecord,
)
from app.persistence.whatsapp_conversation import (
    SQLiteWhatsAppConversationRepository,
)
from app.web.access import BusinessAccessDenied, BusinessAccessService
from app.whatsapp.identity import WhatsAppIdentityResolver
from app.whatsapp.provider import (
    WhatsAppProvider,
    WhatsAppProviderError,
    WhatsAppProviderOutcomeUnknown,
)
from app.whatsapp.security import hash_sender_id, normalize_sender_id


class WhatsAppPayloadError(ValueError):
    """Inbound WhatsApp data is malformed or unsupported."""


class WhatsAppDuplicateMessage(RuntimeError):
    """The provider message has already been claimed or processed."""


class WhatsAppChannelError(RuntimeError):
    """A safe WhatsApp channel failure."""


@dataclass(frozen=True)
class WhatsAppInboundEnvelope:
    provider: str
    provider_account_id: str
    provider_message_id: str
    sender_id: str
    text: str

    def __post_init__(self) -> None:
        for name, value in {
            "provider": self.provider,
            "provider_account_id": self.provider_account_id,
            "provider_message_id": self.provider_message_id,
            "sender_id": self.sender_id,
            "text": self.text,
        }.items():
            if not isinstance(value, str) or not value.strip():
                raise WhatsAppPayloadError(
                    f"{name} must be a non-empty string."
                )

        if len(self.provider_message_id) > 512:
            raise WhatsAppPayloadError(
                "provider_message_id is too long."
            )

        if len(self.text) > 32768:
            raise WhatsAppPayloadError(
                "WhatsApp message is too long."
            )


class WhatsAppChannelService:
    """
    Durable channel boundary.

    The Assistant Core is executed only during the initial PROCESSING state.
    Recovery states never call the Core again.
    """

    def __init__(
        self,
        repository: SQLiteWhatsAppRepository,
        identity_resolver: WhatsAppIdentityResolver,
        commercial_access: BusinessAccessService,
        orchestrator_factory: Callable[
            [TenantContext],
            AssistantOrchestrator,
        ],
        provider: WhatsAppProvider,
        conversation_repository: SQLiteWhatsAppConversationRepository,
        sender_hash_secret: str,
        clock: Callable[..., datetime] = datetime.now,
    ) -> None:
        if not isinstance(repository, SQLiteWhatsAppRepository):
            raise TypeError("repository must be a SQLiteWhatsAppRepository.")

        if not isinstance(
            identity_resolver,
            WhatsAppIdentityResolver,
        ):
            raise TypeError(
                "identity_resolver must be a WhatsAppIdentityResolver."
            )

        if not isinstance(
            commercial_access,
            BusinessAccessService,
        ):
            raise TypeError(
                "commercial_access must be a BusinessAccessService."
            )

        if not callable(orchestrator_factory):
            raise TypeError(
                "orchestrator_factory must be callable."
            )

        if not isinstance(provider, WhatsAppProvider):
            raise TypeError(
                "provider must be a WhatsAppProvider."
            )

        if not isinstance(
            conversation_repository,
            SQLiteWhatsAppConversationRepository,
        ):
            raise TypeError(
                "conversation_repository must be a "
                "SQLiteWhatsAppConversationRepository."
            )

        if not isinstance(sender_hash_secret, str) or not sender_hash_secret:
            raise ValueError(
                "sender_hash_secret must be non-empty."
            )

        self._repository = repository
        self._identity_resolver = identity_resolver
        self._commercial_access = commercial_access
        self._orchestrator_factory = orchestrator_factory
        self._provider = provider
        self._conversation_repository = conversation_repository
        self._sender_hash_secret = sender_hash_secret
        self._clock = clock

    def process(
        self,
        envelope: WhatsAppInboundEnvelope,
    ) -> str:
        if not isinstance(
            envelope,
            WhatsAppInboundEnvelope,
        ):
            raise TypeError(
                "envelope must be a WhatsAppInboundEnvelope."
            )

        received_at = self._aware_now()

        sender_hash = hash_sender_id(
            envelope.sender_id,
            self._sender_hash_secret,
        )

        claimed = self._repository.claim_message(
            provider=envelope.provider,
            provider_account_id=envelope.provider_account_id,
            provider_message_id=envelope.provider_message_id,
            sender_id_hash=sender_hash,
            received_at=received_at,
            inbound_text=envelope.text,
        )

        if not claimed:
            return self._recover_existing(
                envelope,
                sender_hash,
            )

        try:
            resolved_identity = (
                self._identity_resolver.resolve_identity(
                    provider=envelope.provider,
                    provider_account_id=envelope.provider_account_id,
                    sender_id=normalize_sender_id(
                        envelope.sender_id
                    ),
                )
            )

            tenant = resolved_identity.tenant
            binding = resolved_identity.binding

            self._commercial_access.require_execution(
                tenant.business_id
            )

            conversation_history = (
                self._conversation_repository.load_history(
                    binding_id=binding.binding_id,
                    business_id=tenant.business_id,
                )
            )

            orchestrator = self._orchestrator_factory(tenant)

            message = AssistantMessage(
                business_id=tenant.business_id,
                content=envelope.text,
            )

            response = orchestrator.handle(
                message=message,
                tenant=tenant,
                conversation_history=conversation_history,
                channel="whatsapp",
            )

            if response.business_id != tenant.business_id:
                raise WhatsAppChannelError(
                    "Assistant response crossed the WhatsApp "
                    "tenant boundary."
                )

            self._repository.prepare_delivery(
                provider=envelope.provider,
                provider_account_id=envelope.provider_account_id,
                provider_message_id=envelope.provider_message_id,
                business_id=tenant.business_id,
                binding_id=binding.binding_id,
                inbound_text=envelope.text,
                response_text=response.message,
            )

            return self._deliver_and_persist(
                envelope=envelope,
                binding_id=binding.binding_id,
                business_id=tenant.business_id,
                inbound_text=envelope.text,
                response_text=response.message,
            )

        except BusinessAccessDenied:
            self._safe_fail(
                envelope,
                "commercial_access_denied",
            )
            raise

        except WhatsAppProviderOutcomeUnknown:
            self._safe_unknown(
                envelope,
                "provider_outcome_unknown",
            )
            raise

        except WhatsAppProviderError:
            self._safe_fail(
                envelope,
                "provider_delivery_failed",
            )
            raise

        except Exception:
            self._safe_fail(
                envelope,
                "processing_failed",
            )
            raise

    def _deliver_and_persist(
        self,
        *,
        envelope: WhatsAppInboundEnvelope,
        binding_id: str,
        business_id: str,
        inbound_text: str,
        response_text: str,
    ) -> str:
        self._repository.mark_delivery_attempted(
            provider=envelope.provider,
            provider_account_id=envelope.provider_account_id,
            provider_message_id=envelope.provider_message_id,
            attempted_at=self._aware_now(),
        )

        try:
            provider_message_id = self._provider.send_text(
                provider_account_id=envelope.provider_account_id,
                recipient=normalize_sender_id(
                    envelope.sender_id
                ),
                text=response_text,
            )
        except WhatsAppProviderOutcomeUnknown:
            self._safe_unknown(
                envelope,
                "provider_outcome_unknown",
            )
            raise
        except WhatsAppProviderError:
            self._safe_fail(
                envelope,
                "provider_delivery_failed",
            )
            raise

        self._repository.mark_delivered(
            provider=envelope.provider,
            provider_account_id=envelope.provider_account_id,
            provider_message_id=envelope.provider_message_id,
            delivered_at=self._aware_now(),
            provider_response_message_id=provider_message_id,
        )

        self._conversation_repository.append_exchange(
            binding_id=binding_id,
            business_id=business_id,
            user_content=inbound_text,
            assistant_content=response_text,
            created_at=self._aware_now(),
            exchange_id=envelope.provider_message_id,
        )

        self._repository.mark_conversation_persisted(
            provider=envelope.provider,
            provider_account_id=envelope.provider_account_id,
            provider_message_id=envelope.provider_message_id,
            persisted_at=self._aware_now(),
        )

        self._repository.complete_message(
            provider=envelope.provider,
            provider_account_id=envelope.provider_account_id,
            provider_message_id=envelope.provider_message_id,
            completed_at=self._aware_now(),
        )

        return response_text

    def _recover_existing(
        self,
        envelope: WhatsAppInboundEnvelope,
        sender_hash: str,
    ) -> str:
        record = self._repository.get_message(
            provider=envelope.provider,
            provider_account_id=envelope.provider_account_id,
            provider_message_id=envelope.provider_message_id,
        )

        if record is None:
            raise WhatsAppDuplicateMessage(
                "WhatsApp message was already claimed."
            )

        if record.sender_id_hash != sender_hash:
            raise WhatsAppChannelError(
                "WhatsApp message identity does not match "
                "the original sender."
            )

        if record.status == DeliveryState.COMPLETED:
            if not record.response_text:
                raise WhatsAppChannelError(
                    "Completed WhatsApp message has no response."
                )
            return record.response_text

        if record.status == DeliveryState.CONVERSATION_PERSISTED:
            if not record.response_text:
                raise WhatsAppChannelError(
                    "Persisted WhatsApp message has no response."
                )

            self._repository.complete_message(
                provider=envelope.provider,
                provider_account_id=envelope.provider_account_id,
                provider_message_id=envelope.provider_message_id,
                completed_at=self._aware_now(),
            )

            return record.response_text

        if record.status == DeliveryState.DELIVERED:
            return self._recover_conversation(record)

        if record.status == DeliveryState.DELIVERY_PENDING:
            if record.delivery_attempted_at is not None:
                self._repository.mark_delivery_unknown(
                    provider=envelope.provider,
                    provider_account_id=envelope.provider_account_id,
                    provider_message_id=envelope.provider_message_id,
                    error_code="delivery_attempt_timestamp_present",
                )
                raise WhatsAppChannelError(
                    "WhatsApp delivery outcome requires reconciliation."
                )

            if (
                record.business_id is None
                or record.binding_id is None
                or record.response_text is None
                or record.inbound_text is None
            ):
                raise WhatsAppChannelError(
                    "WhatsApp delivery record is incomplete."
                )

            return self._deliver_and_persist(
                envelope=envelope,
                binding_id=record.binding_id,
                business_id=record.business_id,
                inbound_text=record.inbound_text,
                response_text=record.response_text,
            )

        if record.status in {
            DeliveryState.DELIVERY_ATTEMPTED,
            DeliveryState.DELIVERY_UNKNOWN,
        }:
            raise WhatsAppChannelError(
                "WhatsApp delivery outcome requires reconciliation; "
                "blind retry is forbidden."
            )

        if record.status == DeliveryState.PROCESSING:
            self._safe_fail(
                envelope,
                "interrupted_before_response_ready",
            )
            raise WhatsAppChannelError(
                "Previous WhatsApp processing was interrupted before "
                "a durable response was prepared."
            )

        raise WhatsAppDuplicateMessage(
            f"WhatsApp message is in terminal state {record.status.value}."
        )

    def _recover_conversation(
        self,
        record: WhatsAppMessageRecord,
    ) -> str:
        if (
            record.business_id is None
            or record.binding_id is None
            or record.inbound_text is None
            or record.response_text is None
        ):
            raise WhatsAppChannelError(
                "Delivered WhatsApp message is missing recovery data."
            )

        self._conversation_repository.append_exchange(
            binding_id=record.binding_id,
            business_id=record.business_id,
            user_content=record.inbound_text,
            assistant_content=record.response_text,
            created_at=record.delivered_at or self._aware_now(),
            exchange_id=record.provider_message_id,
        )

        self._repository.mark_conversation_persisted(
            provider=record.provider,
            provider_account_id=record.provider_account_id,
            provider_message_id=record.provider_message_id,
            persisted_at=self._aware_now(),
        )

        self._repository.complete_message(
            provider=record.provider,
            provider_account_id=record.provider_account_id,
            provider_message_id=record.provider_message_id,
            completed_at=self._aware_now(),
        )

        return record.response_text

    def _safe_fail(
        self,
        envelope: WhatsAppInboundEnvelope,
        error_code: str,
    ) -> None:
        try:
            self._repository.fail_message(
                provider=envelope.provider,
                provider_account_id=envelope.provider_account_id,
                provider_message_id=envelope.provider_message_id,
                completed_at=self._aware_now(),
                error_code=error_code,
            )
        except Exception:
            pass

    def _safe_unknown(
        self,
        envelope: WhatsAppInboundEnvelope,
        error_code: str,
    ) -> None:
        try:
            self._repository.mark_delivery_unknown(
                provider=envelope.provider,
                provider_account_id=envelope.provider_account_id,
                provider_message_id=envelope.provider_message_id,
                error_code=error_code,
            )
        except Exception:
            pass

    def _aware_now(self) -> datetime:
        try:
            value = self._clock(timezone.utc)
        except TypeError:
            value = self._clock()

        if value.tzinfo is None or value.utcoffset() is None:
            value = value.replace(tzinfo=timezone.utc)

        return value.astimezone(timezone.utc)
