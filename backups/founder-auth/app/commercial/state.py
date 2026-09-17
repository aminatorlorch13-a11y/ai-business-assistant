from dataclasses import dataclass
from enum import Enum


class CommercialStatus(str, Enum):
    """
    Lifecycle state of a business within the commercial platform.

    Commercial status does not itself authorize capabilities or determine
    pricing. It describes the business's current commercial relationship.
    """

    TRIAL = "trial"
    ACTIVE = "active"
    EXPIRED = "expired"
    SUSPENDED = "suspended"


@dataclass(frozen=True)
class BusinessCommercialState:
    """
    Immutable commercial state for one business.
    """

    business_id: str
    status: CommercialStatus

    def __post_init__(self) -> None:
        if not isinstance(self.business_id, str):
            raise TypeError("business_id must be a string.")

        if not self.business_id.strip():
            raise ValueError(
                "business_id must be a non-empty string."
            )

        if not isinstance(self.status, CommercialStatus):
            raise TypeError(
                "status must be a CommercialStatus."
            )
