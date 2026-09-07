from dataclasses import dataclass
from enum import Enum

from app.commercial.purchase import VerifiedPurchase


class PaymentVerificationStatus(str, Enum):
    VERIFIED = "verified"
    REJECTED = "rejected"


@dataclass(frozen=True)
class PaymentVerificationResult:
    """
    Immutable outcome of semantic payment verification.

    VERIFIED results contain a trusted VerifiedPurchase.

    REJECTED results contain no purchase.

    Duplicate detection is intentionally outside this object.
    """

    status: PaymentVerificationStatus
    purchase: VerifiedPurchase | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, PaymentVerificationStatus):
            raise TypeError("status must be a PaymentVerificationStatus.")

        if self.reason is not None:
            if not isinstance(self.reason, str):
                raise TypeError("reason must be a string when provided.")

            if not self.reason.strip():
                raise ValueError("reason must be non-empty when provided.")

        if self.status is PaymentVerificationStatus.VERIFIED:
            if not isinstance(self.purchase, VerifiedPurchase):
                raise ValueError(
                    "verified results must contain a VerifiedPurchase."
                )

            if self.reason is not None:
                raise ValueError(
                    "verified results must not contain a rejection reason."
                )

            return

        if self.purchase is not None:
            raise ValueError(
                "rejected results must not contain a purchase."
            )

        if self.reason is None:
            raise ValueError(
                "rejected results must contain a reason."
            )
