from datetime import datetime, timezone

from app.identity.models import User, BusinessMembership, UserRole
from app.auth.passwords import ScryptPasswordHasher
from app.persistence.user_repository import SQLiteUserRepository
from app.persistence.credential_repository import SQLiteCredentialRepository
from app.persistence.membership_repository import SQLiteMembershipRepository

from test_web_application import make_app, signup, login, csrf


def test_owner_lifestyle_api_update_observe_and_approve(tmp_path):
    app, _ = make_app(tmp_path)
    client = app.test_client()

    signup(client)
    login(client)

    response = client.get("/api/owner/lifestyle")
    assert response.status_code == 200
    assert response.get_json()["initiative_level"] == "balanced"
    assert response.get_json()["personality"] == "natural"

    token = client.get_cookie("assistant_csrf").value

    # Mutations must reject requests without CSRF protection.
    rejected = client.put(
        "/api/owner/lifestyle",
        json={"changes": {"wake_time": "06:00"}},
    )
    assert rejected.status_code == 403

    response = client.put(
        "/api/owner/lifestyle",
        json={
            "changes": {
                "timezone": "Africa/Johannesburg",
                "wake_time": "06:00",
                "sleep_time": "22:00",
            }
        },
        headers={"X-CSRF-Token": token},
    )
    assert response.status_code == 200
    assert response.get_json()["wake_time"] == "06:00"

    # Repeated observations create a suggestion, not an automatic change.
    for _ in range(3):
        response = client.post(
            "/api/owner/lifestyle/observations",
            json={
                "field_name": "wake_time",
                "proposed_value": "06:15",
            },
            headers={"X-CSRF-Token": token},
        )
        assert response.status_code == 201

    suggestions = client.get(
        "/api/owner/lifestyle/suggestions"
    )
    assert suggestions.status_code == 200

    matching = [
        item for item in suggestions.get_json()["suggestions"]
        if item["field_name"] == "wake_time"
        and item["proposed_value"] == "06:15"
    ]
    assert matching

    suggestion_id = matching[0]["suggestion_id"]
    response = client.post(
        f"/api/owner/lifestyle/suggestions/{suggestion_id}/resolve",
        json={"accept": True},
        headers={"X-CSRF-Token": token},
    )
    assert response.status_code == 200
    assert response.get_json()["wake_time"] == "06:15"

    # Verify the accepted value survives a fresh read.
    assert client.get("/api/owner/lifestyle").get_json()["wake_time"] == "06:15"


def test_business_member_cannot_access_owner_lifestyle_api(tmp_path):
    app, db = make_app(tmp_path)
    owner_client = app.test_client()

    signup(owner_client)
    login(owner_client)

    business_id = owner_client.get("/api/me").get_json()["business_id"]

    member = User(
        "lifestyle-member",
        "Member",
        "lifestyle-member@example.com",
    )
    SQLiteUserRepository(db).save(member)
    SQLiteCredentialRepository(db).save(
        member.user_id,
        ScryptPasswordHasher().hash("member-password"),
        at=datetime.now(timezone.utc),
    )
    SQLiteMembershipRepository(db).save(
        BusinessMembership(
            member.user_id,
            business_id,
            UserRole.MEMBER,
        )
    )

    member_client = app.test_client()
    token = csrf(member_client)
    response = member_client.post(
        "/api/auth/login",
        json={
            "email": "lifestyle-member@example.com",
            "password": "member-password",
        },
        headers={"X-CSRF-Token": token},
    )
    assert response.status_code == 200

    assert member_client.get("/api/owner/lifestyle").status_code == 403
    assert member_client.get(
        "/api/owner/lifestyle/suggestions"
    ).status_code == 403

    member_token = member_client.get_cookie("assistant_csrf").value
    response = member_client.put(
        "/api/owner/lifestyle",
        json={"changes": {"wake_time": "05:00"}},
        headers={"X-CSRF-Token": member_token},
    )
    assert response.status_code == 403


def test_owner_attention_api_ingests_persists_and_deduplicates(tmp_path):
    app, db = make_app(tmp_path)
    client = app.test_client()

    signup(client)
    login(client)

    token = client.get_cookie("assistant_csrf").value
    business_id = client.get("/api/me").get_json()["business_id"]

    event_data = {
        "idempotency_key": "customer-payment-overdue-001",
        "event_type": "payment.overdue",
        "severity": "important",
        "title": "Customer payment is overdue",
        "details": "Payment has not been received.",
        "payload": {"invoice_id": "INV-001"},
    }

    # Missing CSRF must be rejected.
    rejected = client.post(
        "/api/owner/attention/events",
        json=event_data,
    )
    assert rejected.status_code == 403

    # Authenticated owner can ingest a valid event.
    response = client.post(
        "/api/owner/attention/events",
        json=event_data,
        headers={"X-CSRF-Token": token},
    )
    assert response.status_code == 201

    event = response.get_json()
    assert event["business_id"] == business_id
    assert event["event_type"] == "payment.overdue"
    assert event["severity"] == "important"
    assert event["title"] == "Customer payment is overdue"

    # Repeating the same idempotency key must not create another event.
    duplicate = client.post(
        "/api/owner/attention/events",
        json=event_data,
        headers={"X-CSRF-Token": token},
    )
    assert duplicate.status_code == 201
    assert duplicate.get_json()["event_id"] == event["event_id"]

    # Verify the event exists in the actual application database.
    with db.connection() as connection:
        rows = connection.execute(
            """
            SELECT event_id, business_id, idempotency_key
            FROM attention_events
            WHERE business_id = ?
              AND idempotency_key = ?
            """,
            (business_id, event_data["idempotency_key"]),
        ).fetchall()

    assert len(rows) == 1
    assert rows[0]["event_id"] == event["event_id"]


def test_owner_attention_api_rejects_invalid_input(tmp_path):
    app, _ = make_app(tmp_path)
    client = app.test_client()

    signup(client)
    login(client)

    token = client.get_cookie("assistant_csrf").value

    response = client.post(
        "/api/owner/attention/events",
        json={
            "idempotency_key": "invalid-severity-001",
            "event_type": "payment.overdue",
            "severity": "urgent",
            "title": "Invalid severity test",
        },
        headers={"X-CSRF-Token": token},
    )

    assert response.status_code == 400


def test_business_member_cannot_ingest_owner_attention_events(tmp_path):
    app, db = make_app(tmp_path)
    owner_client = app.test_client()

    signup(owner_client)
    login(owner_client)

    business_id = owner_client.get("/api/me").get_json()["business_id"]

    member = User(
        "attention-member",
        "Member",
        "attention-member@example.com",
    )
    SQLiteUserRepository(db).save(member)
    SQLiteCredentialRepository(db).save(
        member.user_id,
        ScryptPasswordHasher().hash("member-password"),
        at=datetime.now(timezone.utc),
    )
    SQLiteMembershipRepository(db).save(
        BusinessMembership(member.user_id, business_id, UserRole.MEMBER)
    )

    member_client = app.test_client()
    token = csrf(member_client)

    response = member_client.post(
        "/api/auth/login",
        json={
            "email": "attention-member@example.com",
            "password": "member-password",
        },
        headers={"X-CSRF-Token": token},
    )
    assert response.status_code == 200

    member_token = member_client.get_cookie("assistant_csrf").value

    response = member_client.post(
        "/api/owner/attention/events",
        json={
            "idempotency_key": "member-attempt-001",
            "event_type": "payment.overdue",
            "severity": "important",
            "title": "Member access attempt",
        },
        headers={"X-CSRF-Token": member_token},
    )

    assert response.status_code == 403
