from __future__ import annotations

import secrets
from collections.abc import Callable

from app.identity.models import UserRole
from app.persistence.whatsapp import SQLiteWhatsAppRepository
from app.whatsapp.models import WhatsAppBinding
from app.whatsapp.security import hash_sender_id, normalize_sender_id


class WhatsAppBindingError(PermissionError):
    """A WhatsApp binding operation was not authorised."""


class WhatsAppBindingService:
    """
    Manages trusted WhatsApp sender bindings.

    Authorisation is delegated to the application's existing trusted
    membership/access policy. This service never trusts a role supplied
    by an inbound WhatsApp message.
    """

    def __init__(
        self,
        *,
        repository: SQLiteWhatsAppRepository,
        sender_hash_secret: str,
        authorize_business_admin: Callable[[str, str], UserRole],
        verify_provider_account: Callable[[str, str, str, str], bool] | None = None,
    ) -> None:
        if not isinstance(repository, SQLiteWhatsAppRepository):
            raise TypeError("repository must be a SQLiteWhatsAppRepository.")
        if not isinstance(sender_hash_secret, str) or not sender_hash_secret:
            raise ValueError("sender_hash_secret must be non-empty.")
        if not callable(authorize_business_admin):
            raise TypeError("authorize_business_admin must be callable.")

        self._repository = repository
        self._sender_hash_secret = sender_hash_secret
        self._authorize = authorize_business_admin
        self._verify_provider_account = verify_provider_account

    def register_sender(
        self,
        *,
        provider: str,
        provider_account_id: str,
        sender_id: str,
        user_id: str,
        business_id: str,
    ) -> WhatsAppBinding:
        self._validate_provider_identity(provider, provider_account_id)

        if not isinstance(user_id, str) or not user_id.strip():
            raise ValueError("user_id must be non-empty.")
        if not isinstance(business_id, str) or not business_id.strip():
            raise ValueError("business_id must be non-empty.")

        role = self._authorize(user_id, business_id)
        if role not in (UserRole.OWNER, UserRole.ADMIN):
            raise WhatsAppBindingError(
                "Only business owners and admins may register WhatsApp senders."
            )

        if self._verify_provider_account is None:
            raise WhatsAppBindingError(
                "WhatsApp business-number ownership verification is not configured."
            )

        verified = self._verify_provider_account(
            provider, provider_account_id, user_id, business_id
        )
        if verified is not True:
            raise WhatsAppBindingError(
                "WhatsApp business-number ownership could not be verified."
            )

        sender_id = normalize_sender_id(sender_id)
        sender_hash = hash_sender_id(sender_id, self._sender_hash_secret)

        existing = self._repository.get_binding(
            provider=provider,
            provider_account_id=provider_account_id,
            sender_id_hash=sender_hash,
        )

        if existing is not None:
            if (
                existing.user_id != user_id
                or existing.business_id != business_id
            ):
                raise WhatsAppBindingError(
                    "This WhatsApp sender is already bound to another identity."
                )
            if existing.active:
                return existing

        binding = WhatsAppBinding(
            binding_id=(
                existing.binding_id
                if existing is not None
                else secrets.token_urlsafe(32)
            ),
            provider=provider,
            provider_account_id=provider_account_id,
            sender_id_hash=sender_hash,
            user_id=user_id,
            business_id=business_id,
            role=role,
            active=True,
        )

        return self._repository.save_binding(binding)

    def revoke_binding(
        self,
        *,
        binding_id: str,
        user_id: str,
        business_id: str,
    ) -> bool:
        if not isinstance(binding_id, str) or not binding_id.strip():
            raise ValueError("binding_id must be non-empty.")

        role = self._authorize(user_id, business_id)
        if role not in (UserRole.OWNER, UserRole.ADMIN):
            raise WhatsAppBindingError(
                "Only business owners and admins may revoke WhatsApp bindings."
            )

        # Never allow a business administrator to revoke another
        # business's binding by guessing its identifier.
        binding = self._find_binding(binding_id)
        if binding is None or binding.business_id != business_id:
            raise WhatsAppBindingError("Binding not found for this business.")

        return self._repository.deactivate_binding(binding_id)

    def _find_binding(self, binding_id: str) -> WhatsAppBinding | None:
        # The repository intentionally exposes lookup by sender identity,
        # not arbitrary binding ID. Revocation therefore uses a dedicated
        # repository method rather than guessing another identity.
        finder = getattr(self._repository, "get_binding_by_id", None)
        if not callable(finder):
            raise RuntimeError(
                "WhatsApp repository must implement get_binding_by_id "
                "before binding revocation can be enabled."
            )
        return finder(binding_id)

    @staticmethod
    def _validate_provider_identity(
        provider: str,
        provider_account_id: str,
    ) -> None:
        if not isinstance(provider, str) or not provider.strip():
            raise ValueError("provider must be non-empty.")
        if (
            not isinstance(provider_account_id, str)
            or not provider_account_id.isdigit()
        ):
            raise ValueError("provider_account_id must contain digits.")
