from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from app.integrations.google_protocol import (
    GOOGLE_GMAIL_READ_SCOPE,
    GOOGLE_TOKEN_ENDPOINT,
    read_google_json_response,
)


class GoogleTokenError(RuntimeError):
    """Safe failure while obtaining a usable Google access token."""


def exchange_google_refresh_token(
    *, refresh_token: str, client_id: str, client_secret: str,
) -> dict:
    if not all(isinstance(value, str) and value for value in (
        refresh_token, client_id, client_secret,
    )):
        raise GoogleTokenError("Google refresh configuration is incomplete.")

    body = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }).encode("ascii")

    request = urllib.request.Request(
        GOOGLE_TOKEN_ENDPOINT,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = read_google_json_response(response)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise GoogleTokenError("Google access-token refresh failed.") from exc

    access_token = payload.get("access_token")
    token_type = payload.get("token_type")
    expires_in = payload.get("expires_in")

    if (
        not isinstance(access_token, str) or not access_token
        or not isinstance(token_type, str) or token_type.lower() != "bearer"
        or isinstance(expires_in, bool)
        or not isinstance(expires_in, (int, float))
        or expires_in <= 0 or expires_in > 86400
    ):
        raise GoogleTokenError("Google returned an invalid refreshed token.")

    granted_scope = payload.get("scope")
    if granted_scope is not None:
        if (
            not isinstance(granted_scope, str)
            or GOOGLE_GMAIL_READ_SCOPE not in granted_scope.split()
        ):
            raise GoogleTokenError(
                "Google refresh response did not retain Gmail read access."
            )

    return payload


class GoogleGmailTokenManager:
    """Resolve and refresh Gmail credentials without exposing tokens to clients."""

    def __init__(
        self, *, integration_service,
        client_id: str, client_secret: str,
    ) -> None:
        self.integration_service = integration_service
        self.client_id = client_id
        self.client_secret = client_secret

    def get_valid_access_token(
        self, *, connection_id: str, business_id: str, user_id: str,
    ) -> str:
        service = self.integration_service
        connection = service.repository.get_connection(
            connection_id=connection_id,
            business_id=business_id,
            user_id=user_id,
        )

        if connection.provider != "gmail" or connection.status != "active":
            raise PermissionError("Active Gmail connection not found.")

        if not service.has_permission(
            connection_id=connection_id,
            business_id=business_id,
            user_id=user_id,
            scope="email.read",
        ):
            raise PermissionError("Gmail read permission is not active.")

        payload = service.read_secret_payload(
            connection_id=connection_id,
            business_id=business_id,
            user_id=user_id,
        )

        access_token = payload.get("access_token")
        refresh_token = payload.get("refresh_token")
        expires_at = payload.get("expires_at")

        if not all(isinstance(value, str) and value for value in (
            access_token, refresh_token, expires_at,
        )):
            raise GoogleTokenError("Stored Gmail credentials are incomplete.")

        try:
            expiry = datetime.fromisoformat(expires_at)
            if expiry.tzinfo is None:
                raise ValueError("Expiry must include a timezone.")
            expiry = expiry.astimezone(timezone.utc)
        except (TypeError, ValueError) as exc:
            raise GoogleTokenError("Stored Gmail token expiry is invalid.") from exc

        now = datetime.now(timezone.utc)
        if expiry > now + timedelta(seconds=90):
            return access_token

        refreshed = exchange_google_refresh_token(
            refresh_token=refresh_token,
            client_id=self.client_id,
            client_secret=self.client_secret,
        )

        new_refresh_token = refreshed.get("refresh_token") or refresh_token
        if not isinstance(new_refresh_token, str) or not new_refresh_token:
            raise GoogleTokenError("Google refresh token is missing.")

        new_scope = refreshed.get("scope")
        if new_scope is None:
            new_scope = payload.get("granted_scopes", "")

        if (
            not isinstance(new_scope, str)
            or GOOGLE_GMAIL_READ_SCOPE not in new_scope.split()
        ):
            raise GoogleTokenError(
                "Google refresh did not retain the required Gmail read permission."
            )

        new_payload = dict(payload)
        new_payload.update({
            "access_token": refreshed["access_token"],
            "refresh_token": new_refresh_token,
            "token_type": "Bearer",
            "expires_at": (
                now + timedelta(seconds=int(refreshed["expires_in"]))
            ).isoformat(),
            "granted_scopes": new_scope,
        })

        service.replace_secret_payload(
            connection_id=connection_id,
            business_id=business_id,
            user_id=user_id,
            expected_payload=payload,
            replacement_payload=new_payload,
        )
        return refreshed["access_token"]
