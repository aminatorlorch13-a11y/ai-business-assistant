from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from typing import Callable

from app.assistant.capability_confirmation import CapabilityConfirmation
from app.assistant.execution import CapabilityExecutionRequest
from app.auth.session_security import hash_session_id
from app.identity.tenant import TenantContext
from app.persistence.capability_confirmation import (
    CapabilityConfirmationRepository,
)


CAPABILITY_CONFIRMATION_TTL = timedelta(minutes=5)


class CapabilityConfirmationService:
    """
    Application service for durable, session-bound capability confirmations.

    This service creates authorization records for exact trusted execution
    requests. It never interprets AI proposals and never executes capabilities.

    Confirmation identity is derived from the authenticated TenantContext.
    The raw session ID is hashed before persistence.
    """

    def __init__(
        self,
        repository: CapabilityConfirmationRepository,
        *,
        clock: Callable[[], datetime] | None = None,
        confirmation_ttl: timedelta = CAPABILITY_CONFIRMATION_TTL,
    ) -> None:
        if not isinstance(confirmation_ttl, timedelta):
            raise TypeError("confirmation_ttl must be a timedelta.")
        if confirmation_ttl <= timedelta(0):
            raise ValueError("confirmation_ttl must be positive.")

        self._repository = repository
        self._clock = clock or datetime.now
        self._confirmation_ttl = confirmation_ttl

    def create(
        self,
        request: CapabilityExecutionRequest,
        *,
        tenant: TenantContext,
    ) -> CapabilityConfirmation:
        if not isinstance(request, CapabilityExecutionRequest):
            raise TypeError(
                "request must be a CapabilityExecutionRequest."
            )
        if not isinstance(tenant, TenantContext):
            raise TypeError("tenant must be a TenantContext.")

        principal = tenant.principal

        if principal.business_id != request.business_id:
            raise PermissionError(
                "Capability confirmation business does not match "
                "the authenticated tenant."
            )

        if principal.role is None:
            raise PermissionError(
                "Capability confirmation requires a business role."
            )

        now = self._now()

        confirmation = CapabilityConfirmation(
            confirmation_id=secrets.token_urlsafe(32),
            session_id_hash=hash_session_id(principal.session_id),
            user_id=principal.user_id,
            business_id=tenant.business_id,
            role=principal.role,
            request=request,
            created_at=now,
            expires_at=now + self._confirmation_ttl,
        )

        self._repository.save_exclusive(confirmation)
        return confirmation

    def consume(
        self,
        confirmation_id: str,
        *,
        tenant: TenantContext,
        channel: str | None,
        integration: str | None,
    ) -> CapabilityConfirmation | None:
        if not isinstance(tenant, TenantContext):
            raise TypeError("tenant must be a TenantContext.")

        principal = tenant.principal

        if principal.business_id != tenant.business_id:
            raise PermissionError(
                "Authenticated principal does not match the tenant."
            )

        if principal.role is None:
            raise PermissionError(
                "Capability confirmation requires a business role."
            )

        return self._repository.consume(
            confirmation_id,
            session_id_hash=hash_session_id(principal.session_id),
            user_id=principal.user_id,
            business_id=tenant.business_id,
            role=principal.role,
            channel=channel,
            integration=integration,
            now=self._now(),
        )

    def revoke(
        self,
        confirmation_id: str,
        *,
        tenant: TenantContext,
        channel: str | None,
        integration: str | None,
    ) -> bool:
        if not isinstance(tenant, TenantContext):
            raise TypeError("tenant must be a TenantContext.")

        principal = tenant.principal

        if principal.business_id != tenant.business_id:
            raise PermissionError(
                "Authenticated principal does not match the tenant."
            )

        if principal.role is None:
            raise PermissionError(
                "Capability confirmation requires a business role."
            )

        return self._repository.revoke(
            confirmation_id,
            session_id_hash=hash_session_id(principal.session_id),
            user_id=principal.user_id,
            business_id=tenant.business_id,
            role=principal.role,
            channel=channel,
            integration=integration,
            now=self._now(),
        )

    def _now(self) -> datetime:
        now = self._clock()
        if not isinstance(now, datetime):
            raise TypeError("clock must return a datetime.")
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime.")
        return now
