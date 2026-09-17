from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import re


_CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")


@dataclass(frozen=True)
class PaymentVerificationRequest:
    """
    Expected commercial facts against which a provider event is checked.

    This contains expectations only. It does not verify a payment and
    does not contain credentials.
    """

    business_id: str
    expected_amount: Decimal
    expected_currency: str
    requested_at: datetime

    def __post_init__(self) -> None:
        self._validate_non_empty_string(
            "business_id",
            self.business_id,
        )

        if not isinstance(self.expected_amount, Decimal):
            raise TypeError(
                "expected_amount must be a Decimal."
            )

        if not self.expected_amount.is_finite():
            raise ValueError(
                "expected_amount must be finite."
            )

        if self.expected_amount <= Decimal("0"):
            raise ValueError(
                "expected_amount must be greater than zero."
            )

        if not isinstance(self.expected_currency, str):
            raise TypeError(
                "expected_currency must be a string."
            )

        if not _CURRENCY_PATTERN.fullmatch(
            self.expected_currency
        ):
            raise ValueError(
                "expected_currency must be exactly "
                "three uppercase letters."
            )

        if not isinstance(self.requested_at, datetime):
            raise TypeError(
                "requested_at must be a datetime."
            )

        if self.requested_at.tzinfo is None:
            raise ValueError(
                "requested_at must be timezone-aware."
            )

        if self.requested_at.utcoffset() is None:
            raise ValueError(
                "requested_at must have a valid UTC offset."
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
