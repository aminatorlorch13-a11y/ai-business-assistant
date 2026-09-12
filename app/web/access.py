from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.commercial.state import CommercialStatus, BusinessCommercialState
from app.commercial.trial import BusinessTrial
from app.persistence.commercial_state_repository import SQLiteCommercialStateRepository
from app.persistence.database import SQLiteDatabase
from app.persistence.trial_repository import SQLiteTrialRepository


class BusinessAccessDenied(PermissionError):
    """The business is not currently entitled to execute assistant work."""


@dataclass(frozen=True)
class BusinessAccess:
    business_id: str
    status: CommercialStatus
    allowed: bool
    reason: str
    trial_ends_at: datetime | None = None


class BusinessAccessService:
    """Resolve commercial execution access without mixing it into auth or UI."""

    def __init__(self, database: SQLiteDatabase, clock=datetime.now) -> None:
        self._states = SQLiteCommercialStateRepository(database)
        self._trials = SQLiteTrialRepository(database)
        self._clock = clock

    def resolve(self, business_id: str) -> BusinessAccess:
        state = self._states.get(business_id)
        if state is None:
            raise BusinessAccessDenied("Business commercial state is missing.")

        now = _aware_utc(self._clock)
        trial = self._trials.get(business_id)

        if state.status == CommercialStatus.TRIAL:
            if trial is None:
                self._states.save(
                    BusinessCommercialState(business_id, CommercialStatus.EXPIRED)
                )
                return BusinessAccess(
                    business_id, CommercialStatus.EXPIRED, False,
                    "Trial information is missing.", None,
                )
            if trial.is_expired(now):
                self._states.save(
                    BusinessCommercialState(business_id, CommercialStatus.EXPIRED)
                )
                return BusinessAccess(
                    business_id, CommercialStatus.EXPIRED, False,
                    "The trial has expired.", trial.ends_at,
                )
            return BusinessAccess(
                business_id, CommercialStatus.TRIAL, True,
                "Trial access is active.", trial.ends_at,
            )

        if state.status == CommercialStatus.ACTIVE:
            return BusinessAccess(
                business_id, CommercialStatus.ACTIVE, True,
                "Business access is active.",
                trial.ends_at if trial else None,
            )

        return BusinessAccess(
            business_id,
            state.status,
            False,
            "Business execution access is suspended.",
            trial.ends_at if trial else None,
        )

    def require_execution(self, business_id: str) -> BusinessAccess:
        access = self.resolve(business_id)
        if not access.allowed:
            raise BusinessAccessDenied(access.reason)
        return access


def _aware_utc(clock) -> datetime:
    try:
        value = clock(timezone.utc)
    except TypeError:
        value = clock()
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
