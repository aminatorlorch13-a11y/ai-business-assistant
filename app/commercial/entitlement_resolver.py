from __future__ import annotations

from app.assistant.capability import Capability
from app.commercial.entitlements import BusinessEntitlements
from app.persistence.capability_entitlement_repository import (
    SQLiteCapabilityEntitlementRepository,
)


class EntitlementResolutionError(PermissionError):
    """Raised when a business has no explicit entitlement configuration."""


class ExplicitEntitlementResolver:
    """Resolve capabilities from the durable application-owned source."""

    def __init__(
        self,
        repository: SQLiteCapabilityEntitlementRepository,
    ) -> None:
        if not isinstance(
            repository,
            SQLiteCapabilityEntitlementRepository,
        ):
            raise TypeError(
                "repository must be a "
                "SQLiteCapabilityEntitlementRepository."
            )

        self._repository = repository

    def resolve(self, business_id: str) -> BusinessEntitlements:
        if not isinstance(business_id, str):
            raise TypeError("business_id must be a string.")

        business_id = business_id.strip()

        if not business_id:
            raise ValueError(
                "business_id must be a non-empty string."
            )

        capabilities = self._repository.get(business_id)

        if capabilities is None:
            raise EntitlementResolutionError(
                "Explicit capability entitlements are not configured "
                f"for business '{business_id}'."
            )

        if not isinstance(capabilities, frozenset):
            raise RuntimeError(
                "Entitlement repository returned an invalid capability set."
            )

        for capability in capabilities:
            if not isinstance(capability, Capability):
                raise RuntimeError(
                    "Entitlement repository returned an invalid capability."
                )

        return BusinessEntitlements(
            business_id=business_id,
            capabilities=capabilities,
        )
