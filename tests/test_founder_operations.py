from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.commercial.purchase import VerifiedPurchase
from app.commercial.purchase_record import PurchaseRecord
from app.commercial.state import BusinessCommercialState, CommercialStatus
from app.commercial.trial import BusinessTrial
from app.founder.models import FounderRecord
from app.founder.operations import FounderOperationsService
from app.identity.models import BusinessMembership, User, UserRole
from app.models.business import Business
from app.persistence.business_repository import SQLiteBusinessRepository
from app.persistence.commercial_repository import SQLitePurchaseStore
from app.persistence.commercial_state_repository import (
    SQLiteCommercialStateRepository,
)
from app.persistence.database import SQLiteDatabase
from app.persistence.founder_repository import SQLiteFounderRepository
from app.persistence.membership_repository import SQLiteMembershipRepository
from app.persistence.platform_event_repository import SQLitePlatformEventRepository
from app.persistence.trial_repository import SQLiteTrialRepository
from app.persistence.user_repository import SQLiteUserRepository
from app.platform.events import (
    PlatformEvent,
    PlatformEventActorType,
    PlatformEventChannel,
    PlatformEventOutcome,
)


NOW = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)


def make_database(tmp_path):
    db = SQLiteDatabase(tmp_path / "assistant.sqlite3")
    db.initialize()
    return db


def make_business(
    business_id: str,
    name: str,
    owner_name: str,
    assistant_name: str,
    voice: str = "male",
) -> Business:
    return Business(
        business_id=business_id,
        name=name,
        owner_name=owner_name,
        assistant_name=assistant_name,
        assistant_voice=voice,
    )


def make_user(user_id: str, name: str, email: str) -> User:
    return User(user_id, name, email)


def add_business(
    db,
    *,
    business_id: str = "business-1",
    name: str = "Example Business",
    owner_user_id: str = "owner-1",
    owner_name: str = "Owner One",
    owner_email: str = "owner@example.com",
    assistant_name: str = "Orbit",
    voice: str = "male",
    status: CommercialStatus = CommercialStatus.ACTIVE,
):
    businesses = SQLiteBusinessRepository(db)
    users = SQLiteUserRepository(db)
    memberships = SQLiteMembershipRepository(db)
    states = SQLiteCommercialStateRepository(db)

    business = make_business(
        business_id,
        name,
        owner_name,
        assistant_name,
        voice,
    )
    user = make_user(owner_user_id, owner_name, owner_email)

    businesses.save(business)
    users.save(user)
    memberships.save(
        BusinessMembership(
            owner_user_id,
            business_id,
            UserRole.OWNER,
        )
    )
    states.save(BusinessCommercialState(business_id, status))

    return business, user


def add_member(db, business_id: str, user_id: str):
    SQLiteUserRepository(db).save(
        make_user(
            user_id,
            f"User {user_id}",
            f"{user_id}@example.com",
        )
    )
    SQLiteMembershipRepository(db).save(
        BusinessMembership(
            user_id,
            business_id,
            UserRole.MEMBER,
        )
    )


def add_trial(db, business_id: str, started_at: datetime):
    SQLiteTrialRepository(db).save(
        BusinessTrial(
            business_id=business_id,
            started_at=started_at,
        )
    )


def add_purchase(
    db,
    *,
    business_id: str,
    event_id: str,
    amount: str = "150.00",
    paid_at: datetime = NOW,
):
    purchase = VerifiedPurchase(
        provider="test-provider",
        provider_event_id=event_id,
        business_id=business_id,
        amount=Decimal(amount),
        currency="ZAR",
        paid_at=paid_at,
    )
    SQLitePurchaseStore(db).save(
        PurchaseRecord(
            purchase=purchase,
            recorded_at=paid_at + timedelta(minutes=1),
        )
    )


def add_event(
    db,
    *,
    business_id: str,
    event_id: str,
    occurred_at: datetime,
    action: str = "assistant.message",
):
    SQLitePlatformEventRepository(db).append(
        PlatformEvent(
            event_id=event_id,
            occurred_at=occurred_at,
            event_type="assistant.operation",
            business_id=business_id,
            user_id=None,
            channel=PlatformEventChannel.WEB,
            actor_type=PlatformEventActorType.USER,
            action=action,
            outcome=PlatformEventOutcome.SUCCESS,
            correlation_id=f"corr-{event_id}",
            metadata={"source": "test"},
        )
    )


def test_founder_operations_lists_businesses_with_owner_and_configuration(
    tmp_path,
):
    db = make_database(tmp_path)
    add_business(
        db,
        business_id="business-1",
        name="Alpha",
        owner_user_id="owner-1",
        owner_name="Alice",
        owner_email="alice@example.com",
        assistant_name="Orbit",
        voice="female",
    )
    add_business(
        db,
        business_id="business-2",
        name="Beta",
        owner_user_id="owner-2",
        owner_name="Bob",
        owner_email="bob@example.com",
        assistant_name="Nova",
        voice="male",
    )

    service = FounderOperationsService(db)

    views = service.list_businesses()

    assert [view.business_id for view in views] == [
        "business-1",
        "business-2",
    ]
    assert views[0].owner == {
        "user_id": "owner-1",
        "display_name": "Alice",
        "email": "alice@example.com",
    }
    assert views[0].assistant == {
        "name": "Orbit",
        "voice": "female",
    }


def test_founder_operations_reports_membership_count(
    tmp_path,
):
    db = make_database(tmp_path)
    add_business(db)
    add_member(db, "business-1", "member-1")
    add_member(db, "business-1", "member-2")

    view = FounderOperationsService(db).get_business("business-1")

    assert view is not None
    assert view.user_count == 3


@pytest.mark.parametrize(
    "status,expected_allowed",
    [
        (CommercialStatus.TRIAL, True),
        (CommercialStatus.ACTIVE, True),
        (CommercialStatus.EXPIRED, False),
        (CommercialStatus.SUSPENDED, False),
    ],
)
def test_founder_operations_exposes_commercial_state(
    tmp_path,
    status,
    expected_allowed,
):
    db = make_database(tmp_path)
    add_business(db, status=status)

    if status == CommercialStatus.TRIAL:
        add_trial(db, "business-1", NOW)

    view = FounderOperationsService(db, clock=lambda: NOW).get_business("business-1")

    assert view is not None
    assert view.commercial["status"] == status.value
    assert view.commercial["execution_allowed"] is expected_allowed


def test_founder_operations_reports_expired_trial_without_mutating_state(
    tmp_path,
):
    db = make_database(tmp_path)
    add_business(db, status=CommercialStatus.TRIAL)

    started_at = NOW - timedelta(days=8)
    add_trial(db, "business-1", started_at)

    service = FounderOperationsService(db, clock=lambda: NOW)
    view = service.get_business("business-1")

    assert view is not None
    assert view.commercial["status"] == CommercialStatus.TRIAL
    assert view.commercial["execution_allowed"] is False
    assert view.commercial["execution_reason"] == "Trial has expired." or (
        view.commercial["execution_reason"] == "The trial has expired."
    )

    state = SQLiteCommercialStateRepository(db).get("business-1")
    assert state is not None
    assert state.status == CommercialStatus.TRIAL


def test_founder_operations_reports_trial_dates(
    tmp_path,
):
    db = make_database(tmp_path)
    add_business(db, status=CommercialStatus.TRIAL)

    started_at = NOW - timedelta(days=2)
    add_trial(db, "business-1", started_at)

    view = FounderOperationsService(db).get_business("business-1")

    assert view is not None
    assert view.commercial["trial_started_at"] == started_at.isoformat()
    assert view.commercial["trial_ends_at"] == (
        started_at + timedelta(days=7)
    ).isoformat()


def test_founder_operations_reports_paid_evidence(
    tmp_path,
):
    db = make_database(tmp_path)
    add_business(db)
    add_purchase(
        db,
        business_id="business-1",
        event_id="payment-1",
        amount="250.00",
    )

    view = FounderOperationsService(db).get_business("business-1")

    assert view is not None
    assert view.commercial["paid"] is True
    assert view.commercial["purchase_count"] == 1
    assert view.commercial["last_purchase"] == {
        "provider": "test-provider",
        "provider_event_id": "payment-1",
        "amount": "250.00",
        "currency": "ZAR",
        "paid_at": NOW.isoformat(),
        "recorded_at": (NOW + timedelta(minutes=1)).isoformat(),
    }


def test_founder_operations_does_not_invent_paid_evidence(
    tmp_path,
):
    db = make_database(tmp_path)
    add_business(db)

    view = FounderOperationsService(db).get_business("business-1")

    assert view is not None
    assert view.commercial["paid"] is False
    assert view.commercial["purchase_count"] == 0
    assert view.commercial["last_purchase"] is None


def test_founder_operations_reports_actual_events(
    tmp_path,
):
    db = make_database(tmp_path)
    add_business(db)
    add_event(
        db,
        business_id="business-1",
        event_id="event-old",
        occurred_at=NOW - timedelta(minutes=10),
    )
    add_event(
        db,
        business_id="business-1",
        event_id="event-new",
        occurred_at=NOW,
    )

    service = FounderOperationsService(db)

    view = service.get_business("business-1")
    events = service.recent_events("business-1")

    assert view is not None
    assert view.operational["recent_event_count"] == 2
    assert view.operational["last_event_at"] == NOW.isoformat()
    assert [event["event_id"] for event in events] == [
        "event-new",
        "event-old",
    ]


def test_founder_operations_global_recent_events_are_available(
    tmp_path,
):
    db = make_database(tmp_path)
    add_business(db, business_id="business-1")
    add_business(
        db,
        business_id="business-2",
        owner_user_id="owner-2",
        owner_name="Owner Two",
        owner_email="owner2@example.com",
    )

    add_event(
        db,
        business_id="business-1",
        event_id="event-1",
        occurred_at=NOW - timedelta(minutes=2),
    )
    add_event(
        db,
        business_id="business-2",
        event_id="event-2",
        occurred_at=NOW,
    )

    events = FounderOperationsService(db).recent_events()

    assert [event["event_id"] for event in events] == [
        "event-2",
        "event-1",
    ]


def test_founder_operations_missing_business_returns_none(
    tmp_path,
):
    db = make_database(tmp_path)

    assert (
        FounderOperationsService(db).get_business("does-not-exist")
        is None
    )


@pytest.mark.parametrize(
    "method,args",
    [
        ("list_businesses", {"limit": 0}),
        ("list_businesses", {"limit": 101}),
        ("recent_events", {"limit": 0}),
        ("recent_events", {"limit": 21}),
    ],
)
def test_founder_operations_rejects_invalid_limits(
    tmp_path,
    method,
    args,
):
    db = make_database(tmp_path)
    service = FounderOperationsService(db)

    with pytest.raises(ValueError):
        getattr(service, method)(**args)


@pytest.mark.parametrize(
    "method,args",
    [
        ("list_businesses", {"limit": True}),
        ("list_businesses", {"limit": "10"}),
        ("recent_events", {"limit": False}),
        ("recent_events", {"limit": "10"}),
    ],
)
def test_founder_operations_rejects_non_integer_limits(
    tmp_path,
    method,
    args,
):
    db = make_database(tmp_path)
    service = FounderOperationsService(db)

    with pytest.raises(TypeError):
        getattr(service, method)(**args)


def test_founder_operations_does_not_expose_platform_secrets(
    tmp_path,
):
    db = make_database(tmp_path)
    add_business(db)
    add_event(
        db,
        business_id="business-1",
        event_id="event-1",
        occurred_at=NOW,
    )

    events = FounderOperationsService(db).recent_events()

    assert events[0]["metadata"] == {"source": "test"}
    assert "password" not in str(events[0]).lower()
    assert "secret" not in str(events[0]).lower()
    assert "token" not in str(events[0]).lower()


def test_founder_operations_returns_none_owner_when_no_owner_membership_exists(
    tmp_path,
):
    db = make_database(tmp_path)
    business = make_business(
        "business-1",
        "Business Without Owner Membership",
        "Configured Owner",
        "Orbit",
    )
    SQLiteBusinessRepository(db).save(business)
    SQLiteCommercialStateRepository(db).save(
        BusinessCommercialState(
            "business-1",
            CommercialStatus.ACTIVE,
        )
    )

    view = FounderOperationsService(db).get_business("business-1")

    assert view is not None
    assert view.owner is None
