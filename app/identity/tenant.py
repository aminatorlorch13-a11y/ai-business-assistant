from __future__ import annotations

from dataclasses import dataclass

from app.identity.models import AuthenticatedPrincipal, BusinessMembership


@dataclass(frozen=True)
class TenantContext:
    """Immutable application context for one authenticated business tenant."""

    business_id: str
    principal: AuthenticatedPrincipal

    def __post_init__(self) -> None:
        if not isinstance(self.business_id, str):
            raise TypeError("business_id must be a string.")
        if not self.business_id.strip():
            raise ValueError("business_id must be a non-empty string.")

        if not isinstance(self.principal, AuthenticatedPrincipal):
            raise TypeError(
                "principal must be an AuthenticatedPrincipal."
            )

        if self.principal.business_id != self.business_id:
            raise ValueError(
                "principal does not belong to the tenant context."
            )

    def require_membership(
        self,
        membership: BusinessMembership,
    ) -> None:
        """Verify that a membership belongs to this authenticated context."""
        if not isinstance(membership, BusinessMembership):
            raise TypeError("membership must be a BusinessMembership.")

        if membership.business_id != self.business_id:
            raise PermissionError(
                "Membership does not belong to the current business."
            )

        if membership.user_id != self.principal.user_id:
            raise PermissionError(
                "Membership does not belong to the authenticated user."
            )

        if membership.role != self.principal.role:
            raise PermissionError(
                "Membership role does not match the authenticated principal."
            )
