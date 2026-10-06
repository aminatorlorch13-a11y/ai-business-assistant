from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime

from app.persistence.business_repository import SQLiteBusinessRepository
from app.persistence.commercial_repository import SQLitePurchaseStore
from app.persistence.commercial_state_repository import (
    SQLiteCommercialStateRepository,
)
from app.persistence.database import SQLiteDatabase
from app.persistence.membership_repository import SQLiteMembershipRepository
from app.persistence.platform_event_repository import (
    SQLitePlatformEventRepository,
)
from app.persistence.trial_repository import SQLiteTrialRepository
from app.persistence.user_repository import SQLiteUserRepository


@dataclass(frozen=True)
class FounderBusinessView:
    business_id: str
    name: str
    owner: dict | None
    assistant: dict
    user_count: int
    commercial: dict
    operational: dict

    def as_dict(self) -> dict:
        return asdict(self)


class FounderOperationsService:
    """Read-only platform operations view for authorized Founders."""

    MAX_BUSINESSES = 100
    MAX_EVENTS = 20
    MAX_PURCHASES = 100

    def __init__(
        self,
        database: SQLiteDatabase,
        *,
        clock=datetime.now,
    ) -> None:
        if not isinstance(database, SQLiteDatabase):
            raise TypeError("database must be a SQLiteDatabase.")
        if not callable(clock):
            raise TypeError("clock must be callable.")

        from app.web.access import BusinessAccessService

        self._access = BusinessAccessService(database, clock=clock)
        self._businesses = SQLiteBusinessRepository(database)
        self._users = SQLiteUserRepository(database)
        self._memberships = SQLiteMembershipRepository(database)
        self._states = SQLiteCommercialStateRepository(database)
        self._trials = SQLiteTrialRepository(database)
        self._purchases = SQLitePurchaseStore(database)
        self._events = SQLitePlatformEventRepository(database)

    def list_businesses(
        self,
        limit: int = MAX_BUSINESSES,
    ) -> list[FounderBusinessView]:
        limit = self._validate_limit(limit, self.MAX_BUSINESSES)

        return [
            self._build_business(business)
            for business in self._businesses.list_all(limit)
        ]

    def get_business(
        self,
        business_id: str,
    ) -> FounderBusinessView | None:
        if not isinstance(business_id, str) or not business_id.strip():
            raise ValueError("business_id must be a non-empty string.")

        business = self._businesses.get(business_id)

        if business is None:
            return None

        return self._build_business(business)

    def recent_events(
        self,
        business_id: str | None = None,
        limit: int = MAX_EVENTS,
    ) -> list[dict]:
        limit = self._validate_limit(limit, self.MAX_EVENTS)

        if business_id is not None:
            events = self._events.list_for_business(
                business_id,
                limit=limit,
            )
        else:
            events = self._events.list_recent(limit=limit)

        return [
            {
                "event_id": event.event_id,
                "occurred_at": event.occurred_at.isoformat(),
                "event_type": event.event_type,
                "business_id": event.business_id,
                "user_id": event.user_id,
                "channel": event.channel.value,
                "actor_type": event.actor_type.value,
                "action": event.action,
                "outcome": event.outcome.value,
                "correlation_id": event.correlation_id,
                "metadata": dict(event.metadata),
            }
            for event in events
        ]

    def _build_business(self, business) -> FounderBusinessView:
        memberships = self._memberships.list_for_business(
            business.business_id
        )

        owner = None

        for membership in memberships:
            if membership.role.value != "owner":
                continue

            user = self._users.get(membership.user_id)

            if user is not None:
                owner = {
                    "user_id": user.user_id,
                    "display_name": user.display_name,
                    "email": user.email,
                }

            break

        state = self._states.get(business.business_id)
        trial = self._trials.get(business.business_id)

        if state is None:
            execution_allowed = False
            execution_reason = "Business commercial state is missing."
        else:
            access = self._access.resolve_read_only(business.business_id)
            execution_allowed = access.allowed
            execution_reason = access.reason

        purchases = self._purchases.list_for_business(
            business.business_id,
            limit=self.MAX_PURCHASES,
        )

        recent_events = self._events.list_for_business(
            business.business_id,
            limit=self.MAX_EVENTS,
        )

        return FounderBusinessView(
            business_id=business.business_id,
            name=business.name,
            owner=owner,
            assistant={
                "name": business.assistant_name,
                "voice": business.assistant_voice,
            },
            user_count=len(memberships),
            commercial={
                "status": state.status.value if state else None,
                "execution_allowed": execution_allowed,
                "execution_reason": execution_reason,
                "trial_started_at": (
                    trial.started_at.isoformat()
                    if trial else None
                ),
                "trial_ends_at": (
                    trial.ends_at.isoformat()
                    if trial else None
                ),
                "paid": bool(purchases),
                "purchase_count": len(purchases),
                "last_purchase": (
                    self._purchase_summary(purchases[0])
                    if purchases else None
                ),
            },
            operational={
                "recent_event_count": len(recent_events),
                "last_event_at": (
                    recent_events[0].occurred_at.isoformat()
                    if recent_events else None
                ),
            },
        )

    @staticmethod
    def _purchase_summary(record) -> dict:
        return {
            "provider": record.provider,
            "provider_event_id": record.provider_event_id,
            "amount": str(record.purchase.amount),
            "currency": record.purchase.currency,
            "paid_at": record.purchase.paid_at.isoformat(),
            "recorded_at": record.recorded_at.isoformat(),
        }

    @staticmethod
    def _validate_limit(value: int, maximum: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("limit must be an integer.")

        if value < 1 or value > maximum:
            raise ValueError(
                f"limit must be between 1 and {maximum}."
            )

        return value
