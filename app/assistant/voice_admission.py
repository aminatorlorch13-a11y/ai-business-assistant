from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from app.assistant.capability import Capability, CapabilityRequest
from app.identity.models import AuthenticatedPrincipal, UserRole
from app.identity.tenant import TenantContext
from app.trust.capability_policy import CapabilityPolicy
from app.web.access import (
    BusinessAccess,
    BusinessAccessDenied,
    BusinessAccessService,
)


class VoiceAdmissionDenied(PermissionError):
    """Raised when a caller cannot open an Assistant Core voice session."""


class AuthenticationBoundary(Protocol):
    def validate_session(
        self,
        session_id: str,
    ) -> AuthenticatedPrincipal:
        ...


@dataclass(frozen=True)
class VoiceSessionAdmission:
    """Trusted immutable result handed to the future voice core."""

    tenant: TenantContext
    access: BusinessAccess
    capability: Capability

    def __post_init__(self) -> None:
        if not isinstance(self.tenant, TenantContext):
            raise TypeError("tenant must be a TenantContext.")

        if not isinstance(self.access, BusinessAccess):
            raise TypeError("access must be a BusinessAccess.")

        if not isinstance(self.capability, Capability):
            raise TypeError("capability must be a Capability.")

        if self.tenant.business_id != self.access.business_id:
            raise ValueError(
                "tenant and commercial access must target the same business."
            )

        if not self.access.allowed:
            raise ValueError(
                "Denied commercial access cannot create admission."
            )

        if self.capability is not Capability.VOICE:
            raise ValueError(
                "Voice admission must authorize the VOICE capability."
            )


class VoiceSessionAdmissionService:
    """
    Trusted admission boundary for Assistant Core voice sessions.

    Existing systems remain authoritative:

        AuthenticationService
              ↓
        AuthenticatedPrincipal
              ↓
        TenantContext
              ↓
        BusinessAccessService
              ↓
        CapabilityPolicy
              ↓
        VoiceSessionAdmission
              ↓
        future Assistant Core
    """

    DEFAULT_ALLOWED_ROLES = frozenset(
        {
            UserRole.OWNER,
            UserRole.ADMIN,
        }
    )

    def __init__(
        self,
        authentication: AuthenticationBoundary,
        commercial_access: BusinessAccessService,
        capability_policy_resolver: Callable[[str], CapabilityPolicy],
        *,
        allowed_roles: frozenset[UserRole] | None = None,
    ) -> None:
        if not hasattr(authentication, "validate_session"):
            raise TypeError(
                "authentication must expose validate_session()."
            )

        if not isinstance(
            commercial_access,
            BusinessAccessService,
        ):
            raise TypeError(
                "commercial_access must be a BusinessAccessService."
            )

        if not callable(capability_policy_resolver):
            raise TypeError(
                "capability_policy_resolver must be callable."
            )

        roles = (
            self.DEFAULT_ALLOWED_ROLES
            if allowed_roles is None
            else allowed_roles
        )

        if not isinstance(roles, frozenset):
            raise TypeError(
                "allowed_roles must be a frozenset."
            )

        if not roles:
            raise ValueError(
                "allowed_roles must not be empty."
            )

        if not roles.issubset(set(UserRole)):
            raise ValueError(
                "allowed_roles contains an invalid role."
            )

        self._authentication = authentication
        self._commercial_access = commercial_access
        self._capability_policy_resolver = capability_policy_resolver
        self._allowed_roles = roles

    def admit_session(
        self,
        session_id: str,
        business_id: str,
    ) -> VoiceSessionAdmission:
        """Authenticate and admit a session to Assistant Core."""

        if not isinstance(session_id, str) or not session_id.strip():
            raise VoiceAdmissionDenied(
                "A valid authenticated session is required."
            )

        if not isinstance(business_id, str) or not business_id.strip():
            raise VoiceAdmissionDenied(
                "A valid business context is required."
            )

        try:
            principal = self._authentication.validate_session(
                session_id,
            )
        except Exception as exc:
            # Do not leak whether the session was expired, revoked,
            # nonexistent, or otherwise invalid.
            raise VoiceAdmissionDenied(
                "Authentication is required."
            ) from exc

        return self.admit_principal(
            principal,
            business_id,
        )

    def admit_principal(
        self,
        principal: AuthenticatedPrincipal,
        business_id: str,
    ) -> VoiceSessionAdmission:
        """
        Transport-neutral admission.

        Future WebSocket/realtime transports can authenticate first and then
        call this method without creating another authorization system.
        """

        if not isinstance(
            principal,
            AuthenticatedPrincipal,
        ):
            raise VoiceAdmissionDenied(
                "Invalid authenticated principal."
            )

        if not isinstance(business_id, str) or not business_id.strip():
            raise VoiceAdmissionDenied(
                "A valid business context is required."
            )

        # Identity ↔ tenant invariant.
        try:
            tenant = TenantContext(
                business_id=business_id,
                principal=principal,
            )
        except (TypeError, ValueError) as exc:
            raise VoiceAdmissionDenied(
                "Authentication does not match the business."
            ) from exc

        # Role authorization.
        if principal.role not in self._allowed_roles:
            raise VoiceAdmissionDenied(
                "This account is not permitted to open a voice session."
            )

        # Commercial execution authorization.
        try:
            access = self._commercial_access.require_execution(
                business_id,
            )
        except BusinessAccessDenied as exc:
            raise VoiceAdmissionDenied(
                str(exc),
            ) from exc

        # Capability authorization.
        try:
            policy = self._capability_policy_resolver(
                business_id,
            )
        except Exception as exc:
            raise VoiceAdmissionDenied(
                "Voice capability authorization is unavailable."
            ) from exc

        if not isinstance(policy, CapabilityPolicy):
            raise TypeError(
                "capability_policy_resolver must return CapabilityPolicy."
            )

        request = CapabilityRequest(
            business_id=business_id,
            capability=Capability.VOICE,
            reason="Open authenticated Assistant Core voice session",
        )

        decision = policy.allows(request)

        if not decision:
            raise VoiceAdmissionDenied(
                "Voice capability is not authorized for this business."
            )

        return VoiceSessionAdmission(
            tenant=tenant,
            access=access,
            capability=Capability.VOICE,
        )
