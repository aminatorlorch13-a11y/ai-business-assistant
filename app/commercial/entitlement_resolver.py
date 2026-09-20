from __future__ import annotations

from collections.abc import Mapping

from app.assistant.capability import Capability
from app.commercial.entitlements import BusinessEntitlements


class EntitlementResolutionError(PermissionError):
    """Raised when a business has no explicit entitlement configuration."""


class ExplicitEntitlementResolver:
    """
    Resolve business capabilities from an explicit application-owned source.

    Commercial lifecycle state is deliberately not inspected here.
    Trial, active, purchase, and launch-program state do not implicitly
    grant capabilities.

    The composition layer supplies the authoritative capability grants.
    """

    def __init__(
        self,
        capabilities_by_business: Mapping[
            str,
            frozenset[Capability],
        ],
    ) -> None:
        if not isinstance(capabilities_by_business, Mapping):
            raise TypeError(
                "capabilities_by_business must be a mapping."
            )

        normalized: dict[str, frozenset[Capability]] = {}

        for business_id, capabilities in capabilities_by_business.items():
            if not isinstance(business_id, str):
                raise TypeError(
                    "Entitlement business IDs must be strings."
                )

            business_id = business_id.strip()

            if not business_id:
                raise ValueError(
                    "Entitlement business IDs must be non-empty."
                )

            if not isinstance(capabilities, frozenset):
                raise TypeError(
                    "Entitlement capability sets must be frozensets."
                )

            for capability in capabilities:
                if not isinstance(capability, Capability):
                    raise TypeError(
                        "Entitlements must contain only Capability values."
                    )

            normalized[business_id] = frozenset(capabilities)

        self._capabilities_by_business = normalized

    def resolve(self, business_id: str) -> BusinessEntitlements:
        if not isinstance(business_id, str):
            raise TypeError("business_id must be a string.")

        business_id = business_id.strip()

        if not business_id:
            raise ValueError(
                "business_id must be a non-empty string."
            )

        capabilities = self._capabilities_by_business.get(business_id)

        if capabilities is None:
            raise EntitlementResolutionError(
                "Explicit capability entitlements are not configured "
                f"for business '{business_id}'."
            )

        return BusinessEntitlements(
            business_id=business_id,
            capabilities=capabilities,
        )
