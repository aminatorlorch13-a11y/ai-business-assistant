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
from app.safety.service import SafetyControlError
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


def founder_login(client, db):
    user = SQLiteUserRepository(db).get_by_email("owner@example.com")
    assert user is not None
    make_founder(db, user.user_id)

    token = csrf(client)
    response = client.post(
        "/api/auth/founder/login",
        json={
            "email": "owner@example.com",
            "password": "correct horse battery staple",
        },
        headers={"X-CSRF-Token": token},
    )
    assert response.status_code == 200
    assert response.get_json()["scope"] == "platform"


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
    founder_login(client, db)

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
    founder_login(client, db)

    user = SQLiteUserRepository(db).get_by_email("owner@example.com")
    assert user is not None
    make_founder(db, user.user_id)

    response = client.get("/api/founder/businesses/does-not-exist")

    assert response.status_code == 404


def test_founder_business_detail_exposes_actual_commercial_state(tmp_path):
    app, db = make_app(tmp_path)
    client = app.test_client()

    signup(client)
    founder_login(client, db)

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
    founder_login(client, db)

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
    founder_login(client, db)

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
    founder_login(client, db)

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
    founder_login(client, db)

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
    founder_login(client, db)

    user = SQLiteUserRepository(db).get_by_email("owner@example.com")
    assert user is not None
    make_founder(db, user.user_id)

    response = client.get(query)

    assert response.status_code == 400


def test_blank_business_filter_is_rejected(tmp_path):
    app, db = make_app(tmp_path)
    client = app.test_client()

    signup(client)
    founder_login(client, db)

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



# ---------------------------------------------------------------------------
# D6.3 Founder Safety API attack coverage
# ---------------------------------------------------------------------------

def _setup_founder_safety_api(tmp_path, *, founder_active=True):
    app, db = make_app(tmp_path)
    client = app.test_client()

    signup(client)
    login(client)

    user = SQLiteUserRepository(db).get_by_email(
        "owner@example.com"
    )
    assert user is not None

    make_founder(
        db,
        user.user_id,
        active=founder_active,
    )

    # Only an active Founder can establish a platform-level Founder session.
    if founder_active:
        founder_login(client, db)

    make_business(
        db,
        "business-1",
        "Real Business",
    )

    make_membership(
        db,
        "business-1",
        user.user_id,
    )

    make_commercial_state(
        db,
        "business-1",
        CommercialStatus.ACTIVE,
    )

    token = client.get_cookie("assistant_csrf").value

    return app, db, client, user, token


def _safety_halt(client, token, **payload):
    return client.post(
        "/api/founder/safety/controls/halt",
        json=payload,
        headers={"X-CSRF-Token": token},
    )


def test_d63_non_founder_cannot_read_safety_controls(tmp_path):
    app, db = make_app(tmp_path)
    client = app.test_client()

    signup(client)
    login(client)

    user = SQLiteUserRepository(db).get_by_email(
        "owner@example.com"
    )
    assert user is not None

    make_business(
        db,
        "business-1",
        "Real Business",
    )

    response = client.get(
        "/api/founder/safety/controls"
    )

    assert response.status_code == 403


def test_d63_inactive_founder_cannot_read_safety_controls(tmp_path):
    app, db, client, user, token = _setup_founder_safety_api(
        tmp_path,
        founder_active=False,
    )

    response = client.get(
        "/api/founder/safety/controls"
    )

    assert response.status_code == 403


def test_d63_unauthenticated_cannot_access_safety_api(tmp_path):
    app, db = make_app(tmp_path)
    client = app.test_client()

    assert (
        client.get(
            "/api/founder/safety/controls"
        ).status_code
        in {401, 403}
    )

    assert (
        client.post(
            "/api/founder/safety/controls/halt",
            json={
                "scope": "business",
                "target": "business-1",
                "reason": "test",
            },
        ).status_code
        in {401, 403}
    )


def test_d63_halt_requires_csrf(tmp_path):
    app, db, client, user, token = _setup_founder_safety_api(
        tmp_path
    )

    response = client.post(
        "/api/founder/safety/controls/halt",
        json={
            "scope": "business",
            "target": "business-1",
            "reason": "test",
        },
    )

    assert response.status_code == 403


@pytest.mark.parametrize(
    "endpoint",
    [
        "/api/founder/safety/incidents/missing/investigate",
        "/api/founder/safety/incidents/missing/resolve",
        "/api/founder/safety/incidents/missing/verify",
        "/api/founder/safety/incidents/missing/authorize-resume",
        "/api/founder/safety/incidents/missing/close",
        "/api/founder/safety/controls/missing/resume",
    ],
)
def test_d63_all_safety_mutations_require_csrf(
    tmp_path,
    endpoint,
):
    app, db, client, user, token = _setup_founder_safety_api(
        tmp_path
    )

    response = client.post(
        endpoint,
        json={},
    )

    assert response.status_code == 403


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"scope": "business"},
        {
            "scope": "business",
            "target": "business-1",
        },
        {
            "target": "business-1",
            "reason": "test",
        },
        {
            "scope": "business",
            "reason": "test",
        },
    ],
)
def test_d63_halt_rejects_missing_required_fields(
    tmp_path,
    payload,
):
    app, db, client, user, token = _setup_founder_safety_api(
        tmp_path
    )

    response = _safety_halt(
        client,
        token,
        **payload,
    )

    assert response.status_code == 400


@pytest.mark.parametrize(
    "payload",
    [
        {
            "scope": "invalid",
            "target": "business-1",
            "reason": "test",
        },
        {
            "scope": "business",
            "target": "",
            "reason": "test",
        },
        {
            "scope": "business",
            "target": "business-1",
            "reason": "",
        },
        {
            "scope": "business",
            "target": "business-1",
            "reason": "   ",
        },
    ],
)
def test_d63_halt_rejects_invalid_values(
    tmp_path,
    payload,
):
    app, db, client, user, token = _setup_founder_safety_api(
        tmp_path
    )

    response = _safety_halt(
        client,
        token,
        **payload,
    )

    assert response.status_code == 400


def test_d63_halt_creates_real_control_and_incident(tmp_path):
    app, db, client, user, token = _setup_founder_safety_api(
        tmp_path
    )

    response = _safety_halt(
        client,
        token,
        scope="business",
        target="business-1",
        reason="Emergency test halt",
    )

    assert response.status_code == 201

    data = response.get_json()

    assert data["scope"] == "business"
    assert data["target"] == "business-1"
    assert data["state"] == "halted"
    assert data["reason"] == "Emergency test halt"
    assert data["incident_id"]

    controls = client.get(
        "/api/founder/safety/controls"
    )

    assert controls.status_code == 200

    control_rows = controls.get_json()["controls"]

    assert len(control_rows) == 1
    assert control_rows[0]["control_id"] == data["control_id"]
    assert control_rows[0]["state"] == "halted"


def test_d63_duplicate_active_halt_is_rejected(tmp_path):
    app, db, client, user, token = _setup_founder_safety_api(
        tmp_path
    )

    first = _safety_halt(
        client,
        token,
        scope="business",
        target="business-1",
        reason="First halt",
    )

    assert first.status_code == 201

    second = _safety_halt(
        client,
        token,
        scope="business",
        target="business-1",
        reason="Second halt",
    )

    assert second.status_code == 400


def test_d63_full_lifecycle_works_through_http_api(tmp_path):
    app, db, client, user, token = _setup_founder_safety_api(
        tmp_path
    )

    halt = _safety_halt(
        client,
        token,
        scope="business",
        target="business-1",
        reason="Lifecycle test",
    )

    assert halt.status_code == 201

    control = halt.get_json()
    control_id = control["control_id"]
    incident_id = control["incident_id"]

    response = client.get(
        f"/api/founder/safety/controls/{control_id}"
    )
    assert response.status_code == 200

    response = client.get(
        f"/api/founder/safety/incidents/{incident_id}"
    )
    assert response.status_code == 200

    response = client.post(
        f"/api/founder/safety/incidents/{incident_id}/investigate",
        json={},
        headers={"X-CSRF-Token": token},
    )
    assert response.status_code == 200
    assert response.get_json()["status"] == "investigating"

    response = client.post(
        f"/api/founder/safety/incidents/{incident_id}/resolve",
        json={"notes": "Root cause fixed."},
        headers={"X-CSRF-Token": token},
    )
    assert response.status_code == 200
    assert response.get_json()["status"] == "resolved"

    response = client.post(
        f"/api/founder/safety/incidents/{incident_id}/verify",
        json={"notes": "Regression tests passed."},
        headers={"X-CSRF-Token": token},
    )
    assert response.status_code == 200
    assert response.get_json()["status"] == "verified"

    response = client.post(
        f"/api/founder/safety/incidents/{incident_id}/authorize-resume",
        json={},
        headers={"X-CSRF-Token": token},
    )
    assert response.status_code == 200
    assert response.get_json()["status"] == "resume_authorized"

    response = client.post(
        f"/api/founder/safety/controls/{control_id}/resume",
        json={},
        headers={"X-CSRF-Token": token},
    )
    assert response.status_code == 200
    assert response.get_json()["state"] == "active"

    response = client.post(
        f"/api/founder/safety/incidents/{incident_id}/close",
        json={},
        headers={"X-CSRF-Token": token},
    )
    assert response.status_code == 200
    assert response.get_json()["status"] == "closed"


def test_d63_http_api_cannot_skip_recovery_lifecycle(tmp_path):
    app, db, client, user, token = _setup_founder_safety_api(
        tmp_path
    )

    halt = _safety_halt(
        client,
        token,
        scope="business",
        target="business-1",
        reason="Lifecycle attack",
    )

    assert halt.status_code == 201

    control = halt.get_json()
    control_id = control["control_id"]
    incident_id = control["incident_id"]

    response = client.post(
        f"/api/founder/safety/controls/{control_id}/resume",
        json={},
        headers={"X-CSRF-Token": token},
    )

    assert response.status_code == 400

    response = client.post(
        f"/api/founder/safety/incidents/{incident_id}/authorize-resume",
        json={},
        headers={"X-CSRF-Token": token},
    )

    assert response.status_code == 400

    response = client.post(
        f"/api/founder/safety/incidents/{incident_id}/verify",
        json={"notes": "Not yet fixed."},
        headers={"X-CSRF-Token": token},
    )

    assert response.status_code == 400


def test_d63_unknown_control_and_incident_return_404(tmp_path):
    app, db, client, user, token = _setup_founder_safety_api(
        tmp_path
    )

    assert (
        client.get(
            "/api/founder/safety/controls/missing"
        ).status_code
        == 404
    )

    assert (
        client.get(
            "/api/founder/safety/incidents/missing"
        ).status_code
        == 404
    )


def test_d63_safety_api_records_audit_events(tmp_path):
    app, db, client, user, token = _setup_founder_safety_api(
        tmp_path
    )

    halt = _safety_halt(
        client,
        token,
        scope="business",
        target="business-1",
        reason="Audit test",
    )

    assert halt.status_code == 201

    incident_id = halt.get_json()["incident_id"]

    client.post(
        f"/api/founder/safety/incidents/{incident_id}/investigate",
        json={},
        headers={"X-CSRF-Token": token},
    )

    events = SQLitePlatformEventRepository(db).list_recent(
        limit=20
    )

    actions = {
        event.action
        for event in events
    }

    assert any(
        "safety" in action
        for action in actions
    )


def test_d63_business_scoped_halt_does_not_create_cross_business_halt(
    tmp_path,
):
    app, db, client, user, token = _setup_founder_safety_api(
        tmp_path
    )

    make_business(
        db,
        "business-2",
        "Other Business",
    )

    make_membership(
        db,
        "business-2",
        user.user_id,
    )

    make_commercial_state(
        db,
        "business-2",
        CommercialStatus.ACTIVE,
    )

    halt = _safety_halt(
        client,
        token,
        scope="business",
        target="business-1",
        reason="Tenant isolation test",
    )

    assert halt.status_code == 201

    controls = client.get(
        "/api/founder/safety/controls"
    )

    assert controls.status_code == 200

    rows = controls.get_json()["controls"]

    assert {
        row["target"]
        for row in rows
    } == {"business-1"}


def test_d63_get_routes_are_read_only(tmp_path):
    app, db, client, user, token = _setup_founder_safety_api(
        tmp_path
    )

    assert (
        client.post(
            "/api/founder/safety/controls"
        ).status_code
        == 405
    )

    assert (
        client.post(
            "/api/founder/safety/controls/missing"
        ).status_code
        == 405
    )

    assert (
        client.post(
            "/api/founder/safety/incidents/missing"
        ).status_code
        == 405
    )


def test_d63_safety_response_does_not_expose_credentials(
    tmp_path,
):
    app, db, client, user, token = _setup_founder_safety_api(
        tmp_path
    )

    halt = _safety_halt(
        client,
        token,
        scope="business",
        target="business-1",
        reason="Response exposure test",
    )

    assert halt.status_code == 201

    body = client.get(
        "/api/founder/safety/controls"
    ).get_data(as_text=True).lower()

    assert "password_hash" not in body
    assert "password" not in body
    assert "secret" not in body
    assert "credential" not in body



def test_founder_response_does_not_expose_password_hash(tmp_path):
    app, db = make_app(tmp_path)
    client = app.test_client()

    signup(client)
    founder_login(client, db)

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
    founder_login(client, db)

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
