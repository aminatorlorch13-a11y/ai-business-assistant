from datetime import datetime, timedelta, timezone

from app.assistant.message import AssistantMessage
from app.assistant.response import AssistantResponse
from app.commercial.trial import BusinessTrial
from app.persistence.database import SQLiteDatabase
from app.persistence.trial_repository import SQLiteTrialRepository
from app.web.application import create_app


from app.identity.models import User, BusinessMembership, UserRole
from app.auth.passwords import ScryptPasswordHasher
from app.persistence.user_repository import SQLiteUserRepository
from app.persistence.credential_repository import SQLiteCredentialRepository
from app.persistence.membership_repository import SQLiteMembershipRepository

class FakeOrchestrator:
    def handle(self, message: AssistantMessage, confirmed: bool = False):
        return AssistantResponse(message.business_id, "Configured Test Assistant", f"Received: {message.content}")


def make_app(tmp_path):
    db = SQLiteDatabase(tmp_path / "assistant.sqlite3")
    app = create_app(database=db, runtime_builder=lambda business: FakeOrchestrator(), testing=True)
    return app, db


def csrf(client):
    client.get("/signup")
    return client.get_cookie("assistant_csrf").value


def signup(client):
    token = csrf(client)
    response = client.post("/api/auth/signup", json={
        "display_name": "Owner", "email": "owner@example.com",
        "password": "correct horse battery staple", "business_name": "Example Business",
        "assistant_name": "Orbit", "assistant_voice": "male",
    }, headers={"X-CSRF-Token": token})
    assert response.status_code == 201


def login(client):
    token = csrf(client)
    response = client.post("/api/auth/login", json={"email": "owner@example.com", "password": "correct horse battery staple"}, headers={"X-CSRF-Token": token})
    assert response.status_code == 200


def test_signup_login_me_and_assistant_execution(tmp_path):
    app, _ = make_app(tmp_path)
    client = app.test_client()
    signup(client)
    login(client)
    payload = client.get("/api/me").get_json()
    assert payload["business"]["assistant_name"] == "Orbit"
    assert payload["commercial"]["allowed"] is True
    response = client.post("/api/assistant/message", json={"message": "read the latest message"}, headers={"X-CSRF-Token": client.get_cookie("assistant_csrf").value})
    assert response.status_code == 200
    assert response.get_json()["message"] == "Received: read the latest message"


def test_owner_can_change_assistant_configuration(tmp_path):
    app, _ = make_app(tmp_path)
    client = app.test_client()
    signup(client)
    login(client)
    response = client.post("/api/business/config", json={"assistant_name": "Friday", "assistant_voice": "female"}, headers={"X-CSRF-Token": client.get_cookie("assistant_csrf").value})
    assert response.status_code == 200
    assert response.get_json()["assistant_name"] == "Friday"


def test_expired_trial_blocks_execution_and_marks_state_expired(tmp_path):
    app, db = make_app(tmp_path)
    client = app.test_client()
    signup(client)
    login(client)
    business_id = client.get("/api/me").get_json()["business_id"]
    old_start = datetime.now(timezone.utc) - timedelta(days=8)
    SQLiteTrialRepository(db).save(BusinessTrial(business_id, old_start))
    assert client.get("/api/me").get_json()["commercial"]["status"] == "expired"
    response = client.post("/api/assistant/message", json={"message": "do work"}, headers={"X-CSRF-Token": client.get_cookie("assistant_csrf").value})
    assert response.status_code == 402



def test_logout_revokes_session_and_blocks_authenticated_requests(tmp_path):
    app, _ = make_app(tmp_path)
    client = app.test_client()

    signup(client)
    login(client)

    assert client.get("/api/me").status_code == 200

    csrf_token = client.get_cookie("assistant_csrf").value
    response = client.post(
        "/api/auth/logout",
        headers={"X-CSRF-Token": csrf_token},
    )

    assert response.status_code == 200
    assert client.get("/api/me").status_code == 401


def test_unauthenticated_assistant_execution_is_rejected(tmp_path):
    app, _ = make_app(tmp_path)
    client = app.test_client()

    csrf_token = csrf(client)
    response = client.post(
        "/api/assistant/message",
        json={"message": "do work"},
        headers={"X-CSRF-Token": csrf_token},
    )

    assert response.status_code == 401



def test_non_owner_cannot_change_assistant_configuration(tmp_path):
    app, db = make_app(tmp_path)
    owner_client = app.test_client()

    signup(owner_client)
    login(owner_client)

    owner_payload = owner_client.get("/api/me").get_json()
    business_id = owner_payload["business_id"]

    member = User(
        "member-test-user",
        "Member",
        "member@example.com",
    )

    hasher = ScryptPasswordHasher()

    SQLiteUserRepository(db).save(member)
    SQLiteCredentialRepository(db).save(
        member.user_id,
        hasher.hash("member-password"),
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
    member_csrf = csrf(member_client)

    login_response = member_client.post(
        "/api/auth/login",
        json={
            "email": "member@example.com",
            "password": "member-password",
        },
        headers={"X-CSRF-Token": member_csrf},
    )

    assert login_response.status_code == 200
    assert login_response.get_json()["business_id"] == business_id

    member_csrf = member_client.get_cookie("assistant_csrf").value

    response = member_client.post(
        "/api/business/config",
        json={
            "assistant_name": "Unauthorized",
            "assistant_voice": "female",
        },
        headers={"X-CSRF-Token": member_csrf},
    )

    assert response.status_code == 403

    # The owner configuration must remain unchanged.
    owner_payload = owner_client.get("/api/me").get_json()
    assert owner_payload["business"]["assistant_name"] == "Orbit"



def test_cross_origin_state_change_is_rejected(tmp_path):
    app, _ = make_app(tmp_path)
    client = app.test_client()
    token = csrf(client)
    response = client.post("/api/auth/login", json={"email": "owner@example.com", "password": "correct horse battery staple"}, headers={"X-CSRF-Token": token, "Origin": "https://attacker.example"})
    assert response.status_code == 403
