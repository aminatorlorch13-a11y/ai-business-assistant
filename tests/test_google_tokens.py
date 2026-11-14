from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.fernet import Fernet

from app.integrations.google_tokens import (
    GoogleGmailTokenManager,
    GoogleTokenError,
)
from app.integrations.security import FernetSecretCipher
from app.integrations.service import IntegrationService
from app.persistence.database import SQLiteDatabase
from app.persistence.integration_repository import SQLiteIntegrationRepository
from app.integrations import google_tokens


def make_service(tmp_path):
    database = SQLiteDatabase(str(tmp_path / "google_tokens.sqlite3"))
    database.initialize()
    repository = SQLiteIntegrationRepository(database)
    cipher = FernetSecretCipher(Fernet.generate_key())
    service = IntegrationService(repository, cipher)
    return database, repository, service


def create_gmail(service, *, expires_seconds=-60, scopes=None):
    expires = (
        datetime.now(timezone.utc) + timedelta(seconds=expires_seconds)
    ).isoformat()
    return service.connect(
        business_id="business-1",
        user_id="user-1",
        provider="gmail",
        external_account_id="google-subject-1",
        scopes=scopes or {"email.read"},
        secret_payload={
            "access_token": "old-access-token",
            "refresh_token": "stable-refresh-token",
            "token_type": "Bearer",
            "expires_at": expires,
            "granted_scopes": (
                "openid email " + google_tokens.GOOGLE_GMAIL_READ_SCOPE
            ),
            "google_subject": "google-subject-1",
            "email": "person@example.com",
        },
        consent_confirmed=True,
    )


def test_valid_access_token_does_not_call_google(tmp_path, monkeypatch):
    _, _, service = make_service(tmp_path)
    connection_id = create_gmail(service, expires_seconds=3600)

    def unexpected(*args, **kwargs):
        raise AssertionError("Refresh should not be called.")

    monkeypatch.setattr(google_tokens, "exchange_google_refresh_token", unexpected)
    manager = GoogleGmailTokenManager(
        integration_service=service,
        client_id="client",
        client_secret="secret",
    )

    token = manager.get_valid_access_token(
        connection_id=connection_id,
        business_id="business-1",
        user_id="user-1",
    )
    assert token == "old-access-token"


def test_expired_token_refreshes_and_preserves_refresh_token(
    tmp_path, monkeypatch,
):
    _, _, service = make_service(tmp_path)
    connection_id = create_gmail(service)

    def fake_refresh(**kwargs):
        assert kwargs["refresh_token"] == "stable-refresh-token"
        return {
            "access_token": "new-access-token",
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": google_tokens.GOOGLE_GMAIL_READ_SCOPE,
        }

    monkeypatch.setattr(
        google_tokens, "exchange_google_refresh_token", fake_refresh
    )
    manager = GoogleGmailTokenManager(
        integration_service=service,
        client_id="client",
        client_secret="secret",
    )

    token = manager.get_valid_access_token(
        connection_id=connection_id,
        business_id="business-1",
        user_id="user-1",
    )

    saved = service.read_secret_payload(
        connection_id=connection_id,
        business_id="business-1",
        user_id="user-1",
    )
    assert token == "new-access-token"
    assert saved["access_token"] == "new-access-token"
    assert saved["refresh_token"] == "stable-refresh-token"
    assert saved["email"] == "person@example.com"


def test_missing_read_permission_blocks_token_use(tmp_path):
    _, _, service = make_service(tmp_path)
    connection_id = create_gmail(service, scopes={"email.send"})
    manager = GoogleGmailTokenManager(
        integration_service=service,
        client_id="client",
        client_secret="secret",
    )

    with pytest.raises(PermissionError):
        manager.get_valid_access_token(
            connection_id=connection_id,
            business_id="business-1",
            user_id="user-1",
        )


def test_invalid_refresh_response_fails_closed(tmp_path, monkeypatch):
    _, _, service = make_service(tmp_path)
    connection_id = create_gmail(service)

    monkeypatch.setattr(
        google_tokens,
        "exchange_google_refresh_token",
        lambda **kwargs: {
            "access_token": "new-token",
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": "openid email",
        },
    )
    manager = GoogleGmailTokenManager(
        integration_service=service,
        client_id="client",
        client_secret="secret",
    )

    with pytest.raises(GoogleTokenError):
        manager.get_valid_access_token(
            connection_id=connection_id,
            business_id="business-1",
            user_id="user-1",
        )


def test_refresh_secret_replacement_rejects_stale_payload(tmp_path):
    _, _, service = make_service(tmp_path)
    connection_id = create_gmail(service)
    current = service.read_secret_payload(
        connection_id=connection_id,
        business_id="business-1",
        user_id="user-1",
    )
    stale = dict(current)
    stale["access_token"] = "stale-access-token"

    with pytest.raises(RuntimeError):
        service.replace_secret_payload(
            connection_id=connection_id,
            business_id="business-1",
            user_id="user-1",
            expected_payload=stale,
            replacement_payload={**stale, "access_token": "replacement"},
        )
