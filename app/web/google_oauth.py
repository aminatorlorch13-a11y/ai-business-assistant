from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from flask import Blueprint, g, jsonify, request

from app.web.auth import login_required, require_csrf
from app.integrations.google_tokens import GoogleGmailTokenManager, GoogleTokenError
from app.integrations.google_gmail import GmailApiClient, GmailApiError



from app.integrations.google_protocol import (
    GOOGLE_GMAIL_READ_SCOPE,
    GOOGLE_TOKEN_ENDPOINT,
    read_google_json_response,
)

GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"
GOOGLE_OIDC_SCOPES = ("openid", "email")


class GoogleOAuthError(RuntimeError):
    """Safe, non-secret Google OAuth operation failure."""


def build_google_authorization_url(
    *, client_id: str, redirect_uri: str, state: str, code_challenge: str,
) -> str:
    if not all(isinstance(v, str) and v.strip() for v in (
        client_id, redirect_uri, state, code_challenge,
    )):
        raise ValueError("Google OAuth configuration is incomplete.")

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join((*GOOGLE_OIDC_SCOPES, GOOGLE_GMAIL_READ_SCOPE)),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
    }
    return GOOGLE_AUTH_ENDPOINT + "?" + urllib.parse.urlencode(params)


def exchange_google_code(
    *, code: str, verifier: str, client_id: str,
    client_secret: str, redirect_uri: str,
) -> dict:
    if not all(isinstance(v, str) and v for v in (
        code, verifier, client_id, client_secret, redirect_uri,
    )):
        raise GoogleOAuthError("Google authorisation could not be completed.")

    body = urllib.parse.urlencode({
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
        "code_verifier": verifier,
    }).encode("ascii")

    req = urllib.request.Request(
        GOOGLE_TOKEN_ENDPOINT,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            payload = read_google_json_response(response)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise GoogleOAuthError("Google token exchange failed.") from exc

    access_token = payload.get("access_token")
    refresh_token = payload.get("refresh_token")
    token_type = payload.get("token_type")
    scope = payload.get("scope")
    expires_in = payload.get("expires_in")

    if (
        not isinstance(access_token, str) or not access_token
        or not isinstance(refresh_token, str) or not refresh_token
        or not isinstance(token_type, str) or token_type.lower() != "bearer"
        or not isinstance(scope, str)
        or GOOGLE_GMAIL_READ_SCOPE not in scope.split()
        or isinstance(expires_in, bool)
        or not isinstance(expires_in, (int, float))
        or expires_in <= 0
        or expires_in > 86400
    ):
        raise GoogleOAuthError(
            "Google did not grant the required durable read-only Gmail access."
        )

    return payload


def fetch_google_userinfo(access_token: str) -> dict:
    if not isinstance(access_token, str) or not access_token:
        raise GoogleOAuthError("Google account verification failed.")

    req = urllib.request.Request(
        GOOGLE_USERINFO_ENDPOINT,
        headers={"Authorization": "Bearer " + access_token},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            payload = read_google_json_response(response)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise GoogleOAuthError("Google account verification failed.") from exc

    subject = payload.get("sub")
    email = payload.get("email")
    verified = payload.get("email_verified")
    if (
        not isinstance(subject, str) or not subject
        or len(subject) > 255
        or not isinstance(email, str) or not email
        or len(email) > 320
        or verified is not True
    ):
        raise GoogleOAuthError("Google account identity could not be verified.")

    return {"sub": subject, "email": email}


def create_google_oauth_blueprint(
    *, integration_service, memberships,
    client_id: str | None, client_secret: str | None,
    redirect_uri: str | None,
) -> Blueprint:
    blueprint = Blueprint("google_oauth", __name__)

    def configuration_ready() -> bool:
        return bool(
            integration_service is not None
            and client_id and client_secret and redirect_uri
        )

    def business_principal():
        principal = getattr(g, "principal", None)
        if (
            principal is None
            or not isinstance(getattr(principal, "user_id", None), str)
            or not principal.user_id
            or not isinstance(getattr(principal, "business_id", None), str)
            or not principal.business_id
            or getattr(principal, "role", None) is None
        ):
            return None
        membership = memberships.get(principal.user_id, principal.business_id)
        if membership is None:
            return None
        return principal

    @blueprint.post("/api/integrations/google/gmail/authorize")
    @login_required
    def authorize_gmail():
        require_csrf()

        if not configuration_ready():
            return jsonify({"error": "Google integration is not configured."}), 503

        principal = business_principal()
        if principal is None:
            return jsonify({"error": "Business access is required."}), 403

        data = request.get_json(silent=True)
        if not isinstance(data, dict) or data.get("consent_confirmed") is not True:
            return jsonify({"error": "Explicit consent is required."}), 400

        try:
            attempt = integration_service.create_oauth_attempt(
                business_id=principal.business_id,
                user_id=principal.user_id,
                provider="gmail",
                redirect_uri=redirect_uri,
                consent_confirmed=True,
                ttl_seconds=600,
            )
            authorization_url = build_google_authorization_url(
                client_id=client_id,
                redirect_uri=redirect_uri,
                state=attempt["state"],
                code_challenge=attempt["code_challenge"],
            )
        except (ValueError, PermissionError, RuntimeError):
            return jsonify({"error": "Could not start Google authorisation."}), 400

        return jsonify({
            "authorization_url": authorization_url,
            "expires_at": attempt["expires_at"],
            "provider": "gmail",
            "requested_access": ["email.read"],
        }), 200

    @blueprint.get("/api/integrations/google/gmail/callback")
    @login_required
    def gmail_callback():
        if not configuration_ready():
            return jsonify({"error": "Google integration is not configured."}), 503

        principal = business_principal()
        if principal is None:
            return jsonify({"error": "Business access is required."}), 403

        state = request.args.get("state", "")
        if not state:
            return jsonify({"error": "Google authorisation could not be verified."}), 400

        try:
            attempt = integration_service.consume_oauth_attempt(
                state=state,
                business_id=principal.business_id,
                user_id=principal.user_id,
                provider="gmail",
                redirect_uri=redirect_uri,
            )
        except (ValueError, PermissionError, RuntimeError):
            return jsonify({"error": "Google authorisation could not be verified."}), 400

        if request.args.get("error"):
            return jsonify({"error": "Google authorisation was not completed."}), 400

        code = request.args.get("code", "")
        if not code or len(code) > 4096:
            return jsonify({"error": "Google authorisation was incomplete."}), 400

        try:
            tokens = exchange_google_code(
                code=code,
                verifier=attempt["code_verifier"],
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=redirect_uri,
            )
            identity = fetch_google_userinfo(tokens["access_token"])

            expires_at = (
                datetime.now(timezone.utc)
                + timedelta(seconds=int(tokens["expires_in"]))
            ).isoformat()

            secret_payload = {
                "access_token": tokens["access_token"],
                "refresh_token": tokens["refresh_token"],
                "token_type": tokens["token_type"],
                "expires_at": expires_at,
                "granted_scopes": tokens["scope"],
                "google_subject": identity["sub"],
                "email": identity["email"],
            }

            connection_id = integration_service.connect(
                business_id=principal.business_id,
                user_id=principal.user_id,
                provider="gmail",
                external_account_id=identity["sub"],
                scopes={"email.read"},
                secret_payload=secret_payload,
                consent_confirmed=True,
            )
        except (GoogleOAuthError, ValueError, PermissionError, RuntimeError):
            return jsonify({"error": "Google Gmail connection could not be saved."}), 400

        return jsonify({
            "connected": True,
            "connection_id": connection_id,
            "provider": "gmail",
            "email": identity["email"],
            "permissions": ["email.read"],
        }), 200


    gmail_api = GmailApiClient()

    def gmail_access_ready() -> bool:
        return bool(configuration_ready() and integration_service is not None)

    def gmail_access_token(principal, connection_id: str) -> str:
        if not isinstance(connection_id, str) or not connection_id or len(connection_id) > 128:
            raise ValueError("Gmail connection ID is invalid.")
        manager = GoogleGmailTokenManager(
            integration_service=integration_service,
            client_id=client_id,
            client_secret=client_secret,
        )
        return manager.get_valid_access_token(
            connection_id=connection_id,
            business_id=principal.business_id,
            user_id=principal.user_id,
        )

    @blueprint.get("/api/integrations/google/gmail/connections/<connection_id>/messages")
    @login_required
    def gmail_messages(connection_id):
        if not gmail_access_ready():
            return jsonify({"error": "Google integration is not configured."}), 503
        principal = business_principal()
        if principal is None:
            return jsonify({"error": "Business access is required."}), 403

        query = request.args.get("q", "")
        page_token = request.args.get("pageToken")
        max_results_raw = request.args.get("maxResults", "25")
        try:
            max_results = int(max_results_raw)
            token = gmail_access_token(principal, connection_id)
            result = gmail_api.list_messages(
                access_token=token,
                query=query,
                page_token=page_token,
                max_results=max_results,
            )
        except ValueError:
            return jsonify({"error": "Gmail search or pagination parameters are invalid."}), 400
        except PermissionError:
            return jsonify({"error": "Active Gmail read permission is required."}), 403
        except (GoogleTokenError, GmailApiError):
            return jsonify({"error": "Gmail messages could not be retrieved."}), 502
        except RuntimeError:
            return jsonify({"error": "Gmail connection could not be accessed."}), 403

        return jsonify(result), 200

    @blueprint.get("/api/integrations/google/gmail/connections/<connection_id>/messages/<message_id>")
    @login_required
    def gmail_message_detail(connection_id, message_id):
        if not gmail_access_ready():
            return jsonify({"error": "Google integration is not configured."}), 503
        principal = business_principal()
        if principal is None:
            return jsonify({"error": "Business access is required."}), 403

        try:
            token = gmail_access_token(principal, connection_id)
            message = gmail_api.get_message(
                access_token=token,
                message_id=message_id,
            )
        except ValueError:
            return jsonify({"error": "Gmail message ID is invalid."}), 400
        except PermissionError:
            return jsonify({"error": "Active Gmail read permission is required."}), 403
        except (GoogleTokenError, GmailApiError):
            return jsonify({"error": "Gmail message could not be retrieved."}), 502
        except RuntimeError:
            return jsonify({"error": "Gmail connection could not be accessed."}), 403

        return jsonify({"message": message}), 200

    return blueprint
