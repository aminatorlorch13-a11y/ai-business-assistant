from dataclasses import dataclass

from app.assistant.capability import Capability, CapabilityRequest
from app.commercial.entitlements import BusinessEntitlements


@dataclass(frozen=True)
class CapabilityPolicy:
    """
    Immutable authorization policy for one business.

    Authorization is explicit and closed-world:
    a capability is permitted only when it is present in
    allowed_capabilities.

    This policy does not perform the capability and does not
    determine commercial pricing or entitlements.
    """

    business_id: str
    allowed_capabilities: frozenset[Capability]

    def __post_init__(self) -> None:
        if not isinstance(self.business_id, str):
            raise TypeError("business_id must be a string.")

        if not self.business_id.strip():
            raise ValueError(
                "business_id must be a non-empty string."
            )

        if not isinstance(
            self.allowed_capabilities,
            frozenset,
        ):
            raise TypeError(
                "allowed_capabilities must be a frozenset."
            )

        for capability in self.allowed_capabilities:
            if not isinstance(capability, Capability):
                raise TypeError(
                    "allowed_capabilities must contain only Capability values."
                )

    @classmethod
    def from_entitlements(
        cls,
        entitlements: BusinessEntitlements,
    ) -> "CapabilityPolicy":
        """
        Build an authorization policy from commercial entitlements.

        Entitlements are the authoritative commercial input. The resulting
        policy remains responsible for authorization decisions.

        Pricing, trial state, and commercial agreement details do not enter
        the capability authorization logic.
        """
        if not isinstance(entitlements, BusinessEntitlements):
            raise TypeError(
                "entitlements must be a BusinessEntitlements."
            )

        return cls(
            business_id=entitlements.business_id,
            allowed_capabilities=entitlements.capabilities,
        )

    def allows(self, request: CapabilityRequest) -> bool:
        """
        Return whether this policy authorizes the requested capability.

        A request is denied when:
        - it is not a CapabilityRequest,
        - it belongs to another business, or
        - its capability is not explicitly allowed.
        """
        if not isinstance(request, CapabilityRequest):
            raise TypeError(
                "request must be a CapabilityRequest."
            )

        if request.business_id != self.business_id:
            return False

        return request.capability in self.allowed_capabilities
