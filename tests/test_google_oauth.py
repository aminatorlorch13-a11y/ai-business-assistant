from __future__ import annotations

import io
import json
import urllib.parse

import pytest

from app.web import google_oauth


def test_authorization_url_requests_read_only_gmail_and_pkce():
    url = google_oauth.build_google_authorization_url(
        client_id="client-id",
        redirect_uri="https://example.com/callback",
        state="state-value",
        code_challenge="challenge-value",
    )
    params = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)

    assert params["response_type"] == ["code"]
    assert params["code_challenge_method"] == ["S256"]
    assert params["code_challenge"] == ["challenge-value"]
    scopes = set(params["scope"][0].split())
    assert scopes == {
        "openid",
        "email",
        google_oauth.GOOGLE_GMAIL_READ_SCOPE,
    }
    assert "https://www.googleapis.com/auth/gmail.send" not in scopes
    assert params["access_type"] == ["offline"]


def test_authorization_url_rejects_missing_configuration():
    with pytest.raises(ValueError):
        google_oauth.build_google_authorization_url(
            client_id="",
            redirect_uri="https://example.com/callback",
            state="state",
            code_challenge="challenge",
        )


def test_token_exchange_rejects_missing_refresh_token(monkeypatch):
    payload = {
        "access_token": "access",
        "token_type": "Bearer",
        "scope": google_oauth.GOOGLE_GMAIL_READ_SCOPE,
        "expires_in": 3600,
    }

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, limit):
            return json.dumps(payload).encode()

    monkeypatch.setattr(
        google_oauth.urllib.request,
        "urlopen",
        lambda *args, **kwargs: FakeResponse(),
    )

    with pytest.raises(google_oauth.GoogleOAuthError):
        google_oauth.exchange_google_code(
            code="code",
            verifier="verifier",
            client_id="client",
            client_secret="secret",
            redirect_uri="https://example.com/callback",
        )


def test_token_exchange_accepts_required_read_only_grant(monkeypatch):
    payload = {
        "access_token": "access",
        "refresh_token": "refresh",
        "token_type": "Bearer",
        "scope": "openid email " + google_oauth.GOOGLE_GMAIL_READ_SCOPE,
        "expires_in": 3600,
    }

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, limit):
            return json.dumps(payload).encode()

    monkeypatch.setattr(
        google_oauth.urllib.request,
        "urlopen",
        lambda *args, **kwargs: FakeResponse(),
    )

    result = google_oauth.exchange_google_code(
        code="code",
        verifier="verifier",
        client_id="client",
        client_secret="secret",
        redirect_uri="https://example.com/callback",
    )
    assert result["access_token"] == "access"
    assert result["refresh_token"] == "refresh"
