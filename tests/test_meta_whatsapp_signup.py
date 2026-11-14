from types import SimpleNamespace

import pytest
from flask import Flask, g

import app.web.meta_whatsapp_signup as routes


class FakeMemberships:
    def __init__(self, role="OWNER"):
        self.role = role

    def get(self, user_id, business_id):
        if user_id != "user-1" or business_id != "business-1":
            return None
        return SimpleNamespace(role=self.role)


class FakeIntegrationService:
    def __init__(self):
        self.created = []
        self.consumed = []
        self.connected = []
        self.used_states = set()

    def create_oauth_attempt(self, **kwargs):
        self.created.append(kwargs)
        return {"state": "one-time-state", "expires_at": "later"}

    def consume_oauth_attempt(self, **kwargs):
        self.consumed.append(kwargs)
        if kwargs["state"] in self.used_states:
            raise PermissionError("Already consumed")
        if (
            kwargs["business_id"] != "business-1"
            or kwargs["user_id"] != "user-1"
            or kwargs["provider"] != routes.PROVIDER
        ):
            raise PermissionError("Wrong tenant or user")
        self.used_states.add(kwargs["state"])
        return {"state": kwargs["state"]}

    def connect(self, **kwargs):
        self.connected.append(kwargs)
        return "connection-1"


@pytest.fixture
def setup_app(monkeypatch):
    monkeypatch.setenv("META_APP_ID", "123456")
    monkeypatch.setenv("META_APP_SECRET", "test-secret")
    monkeypatch.setenv("META_GRAPH_API_VERSION", "v23.0")
    monkeypatch.setenv("META_EMBEDDED_SIGNUP_CONFIG_ID", "987654")
    monkeypatch.setenv(
        "META_EMBEDDED_SIGNUP_REDIRECT_URI",
        "https://example.test/integrations/whatsapp/connect",
    )

    integration = FakeIntegrationService()
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="test-secret")
    app.register_blueprint(
        routes.create_meta_whatsapp_signup_blueprint(
            integration_service=integration,
            memberships=FakeMemberships(),
        )
    )

    @app.before_request
    def set_test_principal():
        if app.config.get("TEST_AUTHENTICATED", True):
            g.principal = SimpleNamespace(
                user_id="user-1",
                business_id="business-1",
            )
        else:
            g.principal = None

    client = app.test_client()
    client.set_cookie("assistant_csrf", "csrf-token")
    return app, client, integration


def csrf_headers():
    return {"X-CSRF-Token": "csrf-token"}


def test_authorize_requires_login(setup_app):
    app, client, _ = setup_app
    app.config["TEST_AUTHENTICATED"] = False

    response = client.post(
        "/api/integrations/meta/whatsapp/authorize",
        json={"consent_confirmed": True},
        headers=csrf_headers(),
    )
    assert response.status_code == 401


def test_authorize_rejects_member(monkeypatch, setup_app):
    app, client, integration = setup_app
    app.view_functions  # Ensure the route is registered.
    # Replace the membership lookup with a non-privileged role.
    route_memberships = routes.create_meta_whatsapp_signup_blueprint
    # The route's membership dependency is supplied when the blueprint is built;
    # this test uses a separate app with a MEMBER membership.
    app2 = Flask("member-test")
    app2.config.update(TESTING=True, SECRET_KEY="test-secret")
    app2.register_blueprint(
        route_memberships(
            integration_service=integration,
            memberships=FakeMemberships("MEMBER"),
        )
    )

    @app2.before_request
    def set_principal():
        g.principal = SimpleNamespace(user_id="user-1", business_id="business-1")

    member_client = app2.test_client()
    member_client.set_cookie("assistant_csrf", "csrf-token")
    response = member_client.post(
        "/api/integrations/meta/whatsapp/authorize",
        json={"consent_confirmed": True},
        headers=csrf_headers(),
    )
    assert response.status_code == 403
    assert integration.created == []


def test_authorize_requires_explicit_consent(setup_app):
    _, client, integration = setup_app
    response = client.post(
        "/api/integrations/meta/whatsapp/authorize",
        json={"consent_confirmed": False},
        headers=csrf_headers(),
    )
    assert response.status_code == 400
    assert integration.created == []


def test_authorize_creates_tenant_bound_attempt(setup_app):
    _, client, integration = setup_app
    response = client.post(
        "/api/integrations/meta/whatsapp/authorize",
        json={"consent_confirmed": True},
        headers=csrf_headers(),
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["state"] == "one-time-state"
    assert body["provider"] == routes.PROVIDER
    assert integration.created == [{
        "business_id": "business-1",
        "user_id": "user-1",
        "provider": routes.PROVIDER,
        "redirect_uri": "https://example.test/integrations/whatsapp/connect",
        "consent_confirmed": True,
        "ttl_seconds": 600,
    }]


def test_authorize_fails_closed_when_configuration_missing(monkeypatch, setup_app):
    _, client, integration = setup_app
    monkeypatch.delenv("META_APP_SECRET")
    response = client.post(
        "/api/integrations/meta/whatsapp/authorize",
        json={"consent_confirmed": True},
        headers=csrf_headers(),
    )
    assert response.status_code == 503
    assert integration.created == []


@pytest.mark.parametrize(
    "waba_id,phone_number_id",
    [
        ("", "123"),
        ("123", ""),
        ("not-numeric", "123"),
        ("123", "not-numeric"),
    ],
)
def test_callback_rejects_invalid_asset_ids(setup_app, waba_id, phone_number_id):
    _, client, integration = setup_app
    response = client.post(
        routes.CALLBACK_PATH,
        json={
            "state": "one-time-state",
            "code": "test-code",
            "waba_id": waba_id,
            "phone_number_id": phone_number_id,
        },
        headers=csrf_headers(),
    )
    assert response.status_code == 400
    assert len(integration.consumed) == 1
    assert integration.connected == []


def test_callback_success_persists_token_and_returns_no_token(monkeypatch, setup_app):
    _, client, integration = setup_app

    class FakeSignupService:
        def __init__(self, *, config, persist_token):
            self.persist_token = persist_token

        def complete_signup(
            self, *, business_id, authorization_code, waba_id, phone_number_id
        ):
            assert business_id == "business-1"
            assert authorization_code == "test-code"
            self.persist_token(
                business_id, waba_id, phone_number_id, "secret-access-token"
            )
            return SimpleNamespace(
                waba_id=waba_id,
                phone_number_id=phone_number_id,
                display_phone_number="+27123456789",
                verified_name="Test Business",
            )

    monkeypatch.setattr(routes, "MetaEmbeddedSignupService", FakeSignupService)

    response = client.post(
        routes.CALLBACK_PATH,
        json={
            "state": "one-time-state",
            "code": "test-code",
            "waba_id": "111222",
            "phone_number_id": "333444",
        },
        headers=csrf_headers(),
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["connected"] is True
    assert body["connection_id"] == "connection-1"
    assert body["sender_binding"] == "not_created"
    assert "access_token" not in body
    assert len(integration.connected) == 1
    saved = integration.connected[0]
    assert saved["business_id"] == "business-1"
    assert saved["user_id"] == "user-1"
    assert saved["external_account_id"] == "111222"
    assert saved["secret_payload"] == {
        "access_token": "secret-access-token",
        "waba_id": "111222",
        "phone_number_id": "333444",
    }
    assert saved["consent_confirmed"] is True


def test_callback_state_is_one_time(setup_app, monkeypatch):
    _, client, integration = setup_app

    class FakeSignupService:
        def __init__(self, *, config, persist_token):
            self.persist_token = persist_token

        def complete_signup(self, *, business_id, authorization_code, waba_id, phone_number_id):
            self.persist_token(business_id, waba_id, phone_number_id, "test-token")
            return SimpleNamespace(
                waba_id=waba_id,
                phone_number_id=phone_number_id,
                display_phone_number="+27123456789",
                verified_name="Test Business",
            )

    monkeypatch.setattr(routes, "MetaEmbeddedSignupService", FakeSignupService)
    payload = {
        "state": "one-time-state",
        "code": "test-code",
        "waba_id": "111222",
        "phone_number_id": "333444",
    }

    first = client.post(routes.CALLBACK_PATH, json=payload, headers=csrf_headers())
    second = client.post(routes.CALLBACK_PATH, json=payload, headers=csrf_headers())

    assert first.status_code == 200
    assert second.status_code == 400
    assert len(integration.consumed) == 2
    assert len(integration.connected) == 1


def test_cross_origin_authorize_is_rejected(setup_app):
    from app.web.security import WebSecurityError

    _, client, integration = setup_app
    with pytest.raises(WebSecurityError):
        client.post(
            "/api/integrations/meta/whatsapp/authorize",
            json={"consent_confirmed": True},
            headers={
                **csrf_headers(),
                "Origin": "https://attacker.example",
            },
        )
    assert integration.created == []
