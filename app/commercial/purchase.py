from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import re


_CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")


@dataclass(frozen=True)
class VerifiedPurchase:
    """
    Immutable fact representing a payment verified by the payment boundary.

    This object records verified payment evidence only.

    It does not:
    - activate a business,
    - authorize capabilities,
    - determine pricing,
    - update the launch program,
    - process payments,
    - store payment credentials,
    - or perform any external side effect.

    A provider event ID is the idempotency identity for the verified
    payment event within its provider namespace.
    """

    provider: str
    provider_event_id: str
    business_id: str
    amount: Decimal
    currency: str
    paid_at: datetime

    def __post_init__(self) -> None:
        self._validate_non_empty_string(
            "provider",
            self.provider,
        )
        self._validate_non_empty_string(
            "provider_event_id",
            self.provider_event_id,
        )
        self._validate_non_empty_string(
            "business_id",
            self.business_id,
        )

        if not isinstance(self.amount, Decimal):
            raise TypeError(
                "amount must be a Decimal."
            )

        if not self.amount.is_finite():
            raise ValueError(
                "amount must be finite."
            )

        if self.amount <= Decimal("0"):
            raise ValueError(
                "amount must be greater than zero."
            )

        if not isinstance(self.currency, str):
            raise TypeError(
                "currency must be a string."
            )

        if not _CURRENCY_PATTERN.fullmatch(self.currency):
            raise ValueError(
                "currency must be exactly three uppercase letters."
            )

        if not isinstance(self.paid_at, datetime):
            raise TypeError(
                "paid_at must be a datetime."
            )

        if self.paid_at.tzinfo is None:
            raise ValueError(
                "paid_at must be timezone-aware."
            )

        if self.paid_at.utcoffset() is None:
            raise ValueError(
                "paid_at must have a valid UTC offset."
            )

    @staticmethod
    def _validate_non_empty_string(
        field_name: str,
        value: object,
    ) -> None:
        if not isinstance(value, str):
            raise TypeError(
                f"{field_name} must be a string."
            )

        if not value.strip():
            raise ValueError(
                f"{field_name} must be a non-empty string."
            )
