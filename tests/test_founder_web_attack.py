from datetime import datetime, timezone

import pytest

from app.commercial.state import BusinessCommercialState, CommercialStatus
from app.founder.models import FounderRecord
from app.identity.models import BusinessMembership, UserRole
from app.models.business import Business
from app.persistence.business_repository import SQLiteBusinessRepository
from app.persistence.commercial_state_repository import (
    SQLiteCommercialStateRepository,
)
from app.persistence.founder_repository import SQLiteFounderRepository
from app.persistence.membership_repository import SQLiteMembershipRepository
from app.persistence.platform_event_repository import (
    SQLitePlatformEventRepository,
)
from app.persistence.trial_repository import SQLiteTrialRepository
from app.persistence.user_repository import SQLiteUserRepository
from app.platform.events import (
    PlatformEvent,
    PlatformEventActorType,
    PlatformEventChannel,
    PlatformEventOutcome,
)


def make_app(tmp_path):
    from tests.test_web_application import make_app as build_app

    return build_app(tmp_path)


def csrf(client):
    client.get("/signup")
    return client.get_cookie("assistant_csrf").value


def signup(client):
    token = csrf(client)
    response = client.post(
        "/api/auth/signup",
        json={
            "display_name": "Owner",
            "email": "owner@example.com",
            "password": "correct horse battery staple",
            "business_name": "Example Business",
            "assistant_name": "Orbit",
            "assistant_voice": "male",
        },
        headers={"X-CSRF-Token": token},
    )
    assert response.status_code == 201


def login(client):
    token = csrf(client)
    response = client.post(
        "/api/auth/login",
        json={
            "email": "owner@example.com",
            "password": "correct horse battery staple",
        },
        headers={"X-CSRF-Token": token},
    )
    assert response.status_code == 200


def make_founder(db, user_id, active=True):
    SQLiteFounderRepository(db).save(
        FounderRecord(
            user_id=user_id,
            active=active,
        )
    )


def make_business(db, business_id, name):
    SQLiteBusinessRepository(db).save(
        Business(
            business_id=business_id,
            name=name,
            owner_name="Owner",
            assistant_name="Orbit",
            assistant_voice="male",
        )
    )


def make_membership(db, business_id, user_id):
    SQLiteMembershipRepository(db).save(
        BusinessMembership(
            user_id=user_id,
            business_id=business_id,
            role=UserRole.OWNER,
        )
    )


def make_commercial_state(db, business_id, status):
    SQLiteCommercialStateRepository(db).save(
        BusinessCommercialState(
            business_id,
            status,
        )
    )


def make_event(db, event_id, business_id, user_id):
    SQLitePlatformEventRepository(db).append(
        PlatformEvent(
            event_id=event_id,
            occurred_at=datetime.now(timezone.utc),
            event_type="assistant.message",
            business_id=business_id,
            user_id=user_id,
            channel=PlatformEventChannel.WEB,
            actor_type=PlatformEventActorType.USER,
            action="assistant.message",
            outcome=PlatformEventOutcome.SUCCESS,
            correlation_id=event_id,
            metadata={"source": "test"},
        )
    )


def test_active_founder_can_list_businesses_across_tenants(tmp_path):
    app, db = make_app(tmp_path)
    client = app.test_client()

    signup(client)
    login(client)

    user = SQLiteUserRepository(db).get_by_email("owner@example.com")
    assert user is not None
    make_founder(db, user.user_id)

    make_business(db, "business-a", "Business A")
    make_business(db, "business-b", "Business B")

    make_commercial_state(db, "business-a", CommercialStatus.ACTIVE)
    make_commercial_state(db, "business-b", CommercialStatus.SUSPENDED)

    response = client.get("/api/founder/businesses")

    assert response.status_code == 200

    data = response.get_json()

    business_ids = {
        item["business_id"]
        for item in data["businesses"]
    }

    assert {"business-a", "business-b"} <= business_ids


def test_non_founder_cannot_access_founder_businesses_api(tmp_path):
    app, _ = make_app(tmp_path)
    client = app.test_client()

    signup(client)
    login(client)

    response = client.get("/api/founder/businesses")

    assert response.status_code == 403


def test_unauthenticated_cannot_access_founder_apis(tmp_path):
    app, _ = make_app(tmp_path)
    client = app.test_client()

    assert client.get("/api/founder/businesses").status_code in {401, 403}
    assert client.get("/api/founder/events").status_code in {401, 403}


def test_inactive_founder_cannot_access_founder_businesses_api(tmp_path):
    app, db = make_app(tmp_path)
    client = app.test_client()

    signup(client)
    login(client)

    user = SQLiteUserRepository(db).get_by_email("owner@example.com")
    assert user is not None
    make_founder(db, user.user_id, active=False)

    response = client.get("/api/founder/businesses")

    assert response.status_code == 403


def test_business_detail_returns_404_for_unknown_business(tmp_path):
    app, db = make_app(tmp_path)
    client = app.test_client()

    signup(client)
    login(client)

    user = SQLiteUserRepository(db).get_by_email("owner@example.com")
    assert user is not None
    make_founder(db, user.user_id)

    response = client.get("/api/founder/businesses/does-not-exist")

    assert response.status_code == 404


def test_founder_business_detail_exposes_actual_commercial_state(tmp_path):
    app, db = make_app(tmp_path)
    client = app.test_client()

    signup(client)
    login(client)

    user = SQLiteUserRepository(db).get_by_email("owner@example.com")
    assert user is not None
    make_founder(db, user.user_id)

    make_business(db, "business-1", "Real Business")
    make_membership(db, "business-1", user.user_id)
    make_commercial_state(
        db,
        "business-1",
        CommercialStatus.SUSPENDED,
    )

    response = client.get("/api/founder/businesses/business-1")

    assert response.status_code == 200

    data = response.get_json()

    assert data["commercial"]["status"] == "suspended"
    assert data["commercial"]["execution_allowed"] is False


def test_founder_business_user_count_is_actual(tmp_path):
    app, db = make_app(tmp_path)
    client = app.test_client()

    signup(client)
    login(client)

    user = SQLiteUserRepository(db).get_by_email("owner@example.com")
    assert user is not None
    make_founder(db, user.user_id)

    make_business(db, "business-1", "Real Business")
    make_membership(db, "business-1", user.user_id)

    response = client.get("/api/founder/businesses/business-1")

    assert response.status_code == 200
    assert response.get_json()["user_count"] == 1


def test_founder_events_returns_recorded_events_only(tmp_path):
    app, db = make_app(tmp_path)
    client = app.test_client()

    signup(client)
    login(client)

    user = SQLiteUserRepository(db).get_by_email("owner@example.com")
    assert user is not None
    make_founder(db, user.user_id)

    make_business(db, "business-1", "Real Business")
    make_event(db, "event-1", "business-1", user.user_id)

    response = client.get("/api/founder/events")

    assert response.status_code == 200

    events = response.get_json()["events"]

    assert len(events) == 1
    assert events[0]["event_id"] == "event-1"
    assert events[0]["business_id"] == "business-1"


def test_founder_events_can_filter_by_business(tmp_path):
    app, db = make_app(tmp_path)
    client = app.test_client()

    signup(client)
    login(client)

    user = SQLiteUserRepository(db).get_by_email("owner@example.com")
    assert user is not None
    make_founder(db, user.user_id)

    make_business(db, "business-a", "Business A")
    make_business(db, "business-b", "Business B")

    make_event(db, "event-a", "business-a", user.user_id)
    make_event(db, "event-b", "business-b", user.user_id)

    response = client.get(
        "/api/founder/events?business_id=business-a"
    )

    assert response.status_code == 200

    events = response.get_json()["events"]

    assert len(events) == 1
    assert events[0]["business_id"] == "business-a"


def test_unknown_business_event_filter_returns_404(tmp_path):
    app, db = make_app(tmp_path)
    client = app.test_client()

    signup(client)
    login(client)

    user = SQLiteUserRepository(db).get_by_email("owner@example.com")
    assert user is not None
    make_founder(db, user.user_id)

    response = client.get(
        "/api/founder/events?business_id=missing-business"
    )

    assert response.status_code == 404


@pytest.mark.parametrize(
    "query",
    [
        "/api/founder/businesses?limit=0",
        "/api/founder/businesses?limit=101",
        "/api/founder/businesses?limit=abc",
        "/api/founder/events?limit=0",
        "/api/founder/events?limit=21",
        "/api/founder/events?limit=abc",
    ],
)
def test_founder_invalid_limits_are_rejected(tmp_path, query):
    app, db = make_app(tmp_path)
    client = app.test_client()

    signup(client)
    login(client)

    user = SQLiteUserRepository(db).get_by_email("owner@example.com")
    assert user is not None
    make_founder(db, user.user_id)

    response = client.get(query)

    assert response.status_code == 400


def test_blank_business_filter_is_rejected(tmp_path):
    app, db = make_app(tmp_path)
    client = app.test_client()

    signup(client)
    login(client)

    user = SQLiteUserRepository(db).get_by_email("owner@example.com")
    assert user is not None
    make_founder(db, user.user_id)

    response = client.get(
        "/api/founder/events?business_id=%20"
    )

    assert response.status_code == 400


def test_founder_apis_are_read_only_get_routes(tmp_path):
    app, db = make_app(tmp_path)
    client = app.test_client()

    signup(client)
    login(client)

    user = SQLiteUserRepository(db).get_by_email("owner@example.com")
    assert user is not None
    make_founder(db, user.user_id)

    assert client.post("/api/founder/businesses").status_code == 405
    assert client.post("/api/founder/events").status_code == 405


def test_founder_response_does_not_expose_password_hash(tmp_path):
    app, db = make_app(tmp_path)
    client = app.test_client()

    signup(client)
    login(client)

    user = SQLiteUserRepository(db).get_by_email("owner@example.com")
    assert user is not None
    make_founder(db, user.user_id)

    make_business(db, "business-1", "Real Business")
    make_membership(db, "business-1", user.user_id)
    make_commercial_state(
        db,
        "business-1",
        CommercialStatus.ACTIVE,
    )

    response = client.get(
        "/api/founder/businesses/business-1"
    )

    assert response.status_code == 200

    body = response.get_data(as_text=True).lower()

    assert "password_hash" not in body
    assert "password" not in body


def test_founder_dashboard_read_is_non_mutating_for_commercial_state(
    tmp_path,
):
    app, db = make_app(tmp_path)
    client = app.test_client()

    signup(client)
    login(client)

    user = SQLiteUserRepository(db).get_by_email("owner@example.com")
    assert user is not None
    make_founder(db, user.user_id)

    make_business(db, "business-1", "Real Business")
    make_membership(db, "business-1", user.user_id)
    make_commercial_state(
        db,
        "business-1",
        CommercialStatus.TRIAL,
    )

    response = client.get(
        "/api/founder/businesses/business-1"
    )

    assert response.status_code == 200
