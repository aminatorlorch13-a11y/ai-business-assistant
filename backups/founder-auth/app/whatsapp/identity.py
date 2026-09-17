from __future__ import annotations

import secrets
from dataclasses import dataclass

from app.identity.models import AuthenticatedPrincipal
from app.identity.tenant import TenantContext
from app.persistence.membership_repository import SQLiteMembershipRepository
from app.persistence.whatsapp import SQLiteWhatsAppRepository
from app.whatsapp.models import WhatsAppBinding
from app.whatsapp.security import hash_sender_id


class WhatsAppIdentityError(PermissionError):
    """The WhatsApp sender cannot be mapped to a trusted business identity."""


@dataclass(frozen=True)
class ResolvedWhatsAppIdentity:
    """
    Trusted identity resolved from a verified WhatsApp sender.

    The binding is returned alongside TenantContext so downstream channel
    services can use the exact authenticated binding as the conversation
    boundary. The binding is never reconstructed from untrusted message data.
    """

    tenant: TenantContext
    binding: WhatsAppBinding


class WhatsAppIdentityResolver:
    """
    Converts a verified provider sender into the same trusted identity model
    already used by the Assistant Core.

    The WhatsApp binding identifies the expected user/business pair, but the
    durable business membership remains authoritative for the user's current
    role and authorization.
    """

    def __init__(
        self,
        repository: SQLiteWhatsAppRepository,
        membership_repository: SQLiteMembershipRepository,
        sender_hash_secret: str,
    ) -> None:
        if not isinstance(repository, SQLiteWhatsAppRepository):
            raise TypeError("repository must be a SQLiteWhatsAppRepository.")

        if not isinstance(
            membership_repository,
            SQLiteMembershipRepository,
        ):
            raise TypeError(
                "membership_repository must be a SQLiteMembershipRepository."
            )

        if not isinstance(sender_hash_secret, str) or not sender_hash_secret:
            raise ValueError("sender_hash_secret must be non-empty.")

        self._repository = repository
        self._membership_repository = membership_repository
        self._sender_hash_secret = sender_hash_secret

    def resolve(
        self,
        provider: str,
        provider_account_id: str,
        sender_id: str,
    ) -> TenantContext:
        """
        Backwards-compatible tenant-only resolution.

        New channel code should use resolve_identity() when it also needs the
        authenticated WhatsApp binding.
        """
        return self.resolve_identity(
            provider=provider,
            provider_account_id=provider_account_id,
            sender_id=sender_id,
        ).tenant

    def resolve_identity(
        self,
        provider: str,
        provider_account_id: str,
        sender_id: str,
    ) -> ResolvedWhatsAppIdentity:
        """
        Resolve both the trusted tenant and the exact authenticated binding.

        The sender hash is derived from the verified inbound sender. The
        resulting database binding and durable membership determine identity.
        No inbound field is trusted to choose business or conversation state.
        """
        sender_hash = hash_sender_id(
            sender_id,
            self._sender_hash_secret,
        )

        binding = self._repository.get_binding(
            provider=provider,
            provider_account_id=provider_account_id,
            sender_id_hash=sender_hash,
        )

        if binding is None or not binding.active:
            raise WhatsAppIdentityError(
                "WhatsApp sender is not registered for an active business."
            )

        membership = self._membership_repository.get(
            user_id=binding.user_id,
            business_id=binding.business_id,
        )

        if membership is None:
            raise WhatsAppIdentityError(
                "WhatsApp sender is not an authorized member of the business."
            )

        # Durable membership is authoritative for the current role.
        # Never trust a stale role stored in the channel binding.
        channel_session_id = (
            f"whatsapp:{binding.provider}:{binding.binding_id}:"
            f"{secrets.token_urlsafe(18)}"
        )

        principal = AuthenticatedPrincipal(
            user_id=membership.user_id,
            business_id=membership.business_id,
            role=membership.role,
            session_id=channel_session_id,
        )

        tenant = TenantContext(
            business_id=membership.business_id,
            principal=principal,
        )

        try:
            tenant.require_membership(membership)
        except PermissionError as exc:
            raise WhatsAppIdentityError(
                "WhatsApp identity does not match the business membership."
            ) from exc

        return ResolvedWhatsAppIdentity(
            tenant=tenant,
            binding=binding,
        )
