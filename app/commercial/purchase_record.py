from dataclasses import dataclass
from datetime import datetime

from app.commercial.purchase import VerifiedPurchase


@dataclass(frozen=True)
class PurchaseRecord:
    """
    Immutable historical record of one processed verified purchase.

    A PurchaseRecord preserves the verified commercial fact together with
    the moment at which the application accepted it for processing.

    This object does not:
    - activate businesses,
    - determine pricing,
    - authorize capabilities,
    - mutate launch-program state,
    - process payments,
    - or contain payment credentials.
    """

    purchase: VerifiedPurchase
    recorded_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.purchase, VerifiedPurchase):
            raise TypeError(
                "purchase must be a VerifiedPurchase."
            )

        if not isinstance(self.recorded_at, datetime):
            raise TypeError(
                "recorded_at must be a datetime."
            )

        if self.recorded_at.tzinfo is None:
            raise ValueError(
                "recorded_at must be timezone-aware."
            )

        if self.recorded_at.utcoffset() is None:
            raise ValueError(
                "recorded_at must have a valid UTC offset."
            )

    @property
    def provider(self) -> str:
        return self.purchase.provider

    @property
    def provider_event_id(self) -> str:
        return self.purchase.provider_event_id

    @property
    def business_id(self) -> str:
        return self.purchase.business_id
