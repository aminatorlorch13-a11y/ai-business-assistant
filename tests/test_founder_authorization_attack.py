import sqlite3
from datetime import datetime, timezone

from app.auth.passwords import ScryptPasswordHasher
from app.founder.authorization import FounderAccessDenied, FounderAuthorizationService
from app.founder.models import FounderRecord
from app.identity.models import AuthenticatedPrincipal, User, UserRole
from app.persistence.credential_repository import SQLiteCredentialRepository
from app.persistence.database import SQLiteDatabase
from app.persistence.founder_repository import SQLiteFounderRepository
from app.persistence.membership_repository import SQLiteMembershipRepository
from app.persistence.user_repository import SQLiteUserRepository
from app.web.application import create_app


def make_app(tmp_path):
    db = SQLiteDatabase(tmp_path / "assistant.sqlite3")
    app = create_app(
        database=db,
        runtime_builder=lambda business: None,
        testing=True,
    )
    return app, db


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


def test_non_founder_is_denied_platform_access(tmp_path):
    app, _ = make_app(tmp_path)
    client = app.test_client()

    signup(client)
    login(client)

    response = client.get("/founder")

    assert response.status_code == 403
    assert response.get_json()["error"] == "Founder access is required."


def test_unauthenticated_founder_access_is_rejected(tmp_path):
    app, _ = make_app(tmp_path)
    client = app.test_client()

    response = client.get("/founder")

    assert response.status_code == 401


def test_active_founder_is_allowed(tmp_path):
    app, db = make_app(tmp_path)
    client = app.test_client()

    signup(client)
    login(client)

    user = SQLiteUserRepository(db).get_by_email("owner@example.com")
    assert user is not None

    SQLiteFounderRepository(db).save(
        FounderRecord(
            user_id=user.user_id,
            active=True,
        )
    )

    response = client.get("/founder")

    assert response.status_code == 200
    assert response.get_json()["user_id"] == user.user_id


def test_inactive_founder_is_denied(tmp_path):
    app, db = make_app(tmp_path)
    client = app.test_client()

    signup(client)
    login(client)

    user = SQLiteUserRepository(db).get_by_email("owner@example.com")
    assert user is not None

    SQLiteFounderRepository(db).save(
        FounderRecord(
            user_id=user.user_id,
            active=False,
        )
    )

    response = client.get("/founder")

    assert response.status_code == 403


def test_unknown_user_is_denied_by_founder_service(tmp_path):
    db = SQLiteDatabase(tmp_path / "assistant.sqlite3")
    db.initialize()

    founders = SQLiteFounderRepository(db)
    service = FounderAuthorizationService(founders)

    principal = AuthenticatedPrincipal(
        user_id="unknown-user",
        business_id="business-1",
        role=UserRole.OWNER,
        session_id="session-1",
    )

    assert service.resolve(principal) is None

    try:
        service.require_founder(principal)
    except FounderAccessDenied:
        pass
    else:
        raise AssertionError("Expected FounderAccessDenied.")


def test_forged_business_id_cannot_create_founder_authority(tmp_path):
    db = SQLiteDatabase(tmp_path / "assistant.sqlite3")
    db.initialize()

    users = SQLiteUserRepository(db)
    users.save(
        User(
            "real-user",
            "Real User",
            "real@example.com",
        )
    )

    founders = SQLiteFounderRepository(db)
    service = FounderAuthorizationService(founders)

    founders.save(
        FounderRecord(
            user_id="real-user",
            active=True,
        )
    )

    forged_principal = AuthenticatedPrincipal(
        user_id="real-user",
        business_id="attacker-business",
        role=UserRole.OWNER,
        session_id="session-forged",
    )

    resolved = service.require_founder(forged_principal)

    assert resolved.user_id == "real-user"
    assert resolved.active is True


def test_founder_authority_is_independent_of_tenant_role(tmp_path):
    db = SQLiteDatabase(tmp_path / "assistant.sqlite3")
    db.initialize()

    users = SQLiteUserRepository(db)
    users.save(
        User(
            "founder-user",
            "Founder User",
            "founder-role@example.com",
        )
    )

    founders = SQLiteFounderRepository(db)
    service = FounderAuthorizationService(founders)

    founders.save(
        FounderRecord(
            user_id="founder-user",
            active=True,
        )
    )

    for role in UserRole:
        principal = AuthenticatedPrincipal(
            user_id="founder-user",
            business_id="business-1",
            role=role,
            session_id=f"session-{role.value}",
        )

        assert service.require_founder(principal).user_id == "founder-user"


def test_revoked_session_cannot_reach_founder_route(tmp_path):
    app, db = make_app(tmp_path)
    client = app.test_client()

    signup(client)
    login(client)

    user = SQLiteUserRepository(db).get_by_email("owner@example.com")
    assert user is not None

    SQLiteFounderRepository(db).save(
        FounderRecord(
            user_id=user.user_id,
            active=True,
        )
    )

    assert client.get("/founder").status_code == 200

    csrf_token = client.get_cookie("assistant_csrf").value

    logout = client.post(
        "/api/auth/logout",
        headers={"X-CSRF-Token": csrf_token},
    )

    assert logout.status_code == 200
    assert client.get("/founder").status_code == 401


def test_founder_record_requires_existing_user(tmp_path):
    db = SQLiteDatabase(tmp_path / "assistant.sqlite3")
    db.initialize()

    founders = SQLiteFounderRepository(db)

    try:
        founders.save(
            FounderRecord(
                user_id="does-not-exist",
                active=True,
            )
        )
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("Founder record must reference an existing user.")


def test_founder_record_can_be_deactivated(tmp_path):
    db = SQLiteDatabase(tmp_path / "assistant.sqlite3")
    db.initialize()

    users = SQLiteUserRepository(db)
    user = User(
        "founder-user",
        "Founder",
        "founder@example.com",
    )
    users.save(user)

    founders = SQLiteFounderRepository(db)

    founders.save(
        FounderRecord(
            user_id=user.user_id,
            active=True,
        )
    )

    assert founders.get(user.user_id).active is True

    founders.set_active(user.user_id, False)

    assert founders.get(user.user_id).active is False
