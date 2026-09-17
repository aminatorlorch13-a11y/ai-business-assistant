from dataclasses import dataclass

from app.assistant.capability import Capability


@dataclass(frozen=True)
class BusinessEntitlements:
    """
    Immutable capabilities commercially entitled to a business.

    Entitlements describe what a business may receive access to under
    its current commercial state. They do not perform authorization,
    execute capabilities, or determine pricing.
    """

    business_id: str
    capabilities: frozenset[Capability]

    def __post_init__(self) -> None:
        if not isinstance(self.business_id, str):
            raise TypeError("business_id must be a string.")

        if not self.business_id.strip():
            raise ValueError(
                "business_id must be a non-empty string."
            )

        if not isinstance(self.capabilities, frozenset):
            raise TypeError(
                "capabilities must be a frozenset."
            )

        for capability in self.capabilities:
            if not isinstance(capability, Capability):
                raise TypeError(
                    "capabilities must contain only Capability values."
                )

    def includes(self, capability: Capability) -> bool:
        """
        Return whether this business is commercially entitled to a capability.
        """
        if not isinstance(capability, Capability):
            raise TypeError(
                "capability must be a Capability."
            )

        return capability in self.capabilities
