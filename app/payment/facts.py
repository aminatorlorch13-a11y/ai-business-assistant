from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import re


_CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")


@dataclass(frozen=True)
class PaymentFacts:
    """
    Provider-neutral semantic facts extracted from a provider event.

    Provider adapters translate provider-specific data into these facts.

    These facts remain untrusted until checked by the semantic verifier.
    """

    business_id: str
    amount: Decimal
    currency: str
    payment_status: str
    paid_at: datetime

    def __post_init__(self) -> None:
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

        self._validate_non_empty_string(
            "payment_status",
            self.payment_status,
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
