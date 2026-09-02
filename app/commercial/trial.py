from dataclasses import dataclass
from datetime import datetime, timedelta


TRIAL_DURATION_DAYS = 7


@dataclass(frozen=True)
class BusinessTrial:
    """
    Immutable 7-day trial period for one business.

    Trial state describes the commercial trial period only.
    It does not authorize capabilities, execute AI actions,
    determine pricing, or process payments.
    """

    business_id: str
    started_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.business_id, str):
            raise TypeError("business_id must be a string.")

        if not self.business_id.strip():
            raise ValueError(
                "business_id must be a non-empty string."
            )

        if not isinstance(self.started_at, datetime):
            raise TypeError(
                "started_at must be a datetime."
            )

        if self.started_at.tzinfo is None:
            raise ValueError(
                "started_at must be timezone-aware."
            )

        if self.started_at.utcoffset() is None:
            raise ValueError(
                "started_at must have a valid UTC offset."
            )

    @property
    def ends_at(self) -> datetime:
        """
        Return the exact instant at which the trial expires.
        """
        return self.started_at + timedelta(
            days=TRIAL_DURATION_DAYS
        )

    def is_expired(self, at: datetime) -> bool:
        """
        Return whether the trial has expired at the supplied instant.

        Expiration occurs at the exact ends_at instant.
        """
        if not isinstance(at, datetime):
            raise TypeError(
                "at must be a datetime."
            )

        if at.tzinfo is None:
            raise ValueError(
                "at must be timezone-aware."
            )

        if at.utcoffset() is None:
            raise ValueError(
                "at must have a valid UTC offset."
            )

        return at >= self.ends_at
