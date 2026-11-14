"""Authenticated Meta WhatsApp Embedded Signup routes."""

import os

from flask import Blueprint, g, jsonify, request, render_template

from app.web.auth import login_required, require_csrf
from app.whatsapp.embedded_signup import (
    MetaEmbeddedSignupConfig,
    MetaEmbeddedSignupError,
    MetaEmbeddedSignupService,
)

PROVIDER = "whatsapp_business"
SCOPES = {"profile.read", "messages.read", "messages.send"}
CALLBACK_PATH = "/api/integrations/meta/whatsapp/callback"


def create_meta_whatsapp_signup_blueprint(*, integration_service, memberships):
    blueprint = Blueprint("meta_whatsapp_signup", __name__)

    def principal_and_role():
        principal = getattr(g, "principal", None)
        if (
            principal is None
            or not isinstance(getattr(principal, "user_id", None), str)
            or not principal.user_id
            or not isinstance(getattr(principal, "business_id", None), str)
            or not principal.business_id
        ):
            return None

        membership = memberships.get(
            principal.user_id, principal.business_id
        )
        if membership is None:
            return None

        role = getattr(membership, "role", None)
        role = getattr(role, "value", role)
        if not isinstance(role, str) or role.upper() not in {"OWNER", "ADMIN"}:
            return None
        return principal

    def configuration():
        if integration_service is None:
            return None
        try:
            meta = MetaEmbeddedSignupConfig.from_environment()
        except (RuntimeError, ValueError):
            return None

        config_id = os.getenv("META_EMBEDDED_SIGNUP_CONFIG_ID")
        redirect_uri = os.getenv("META_EMBEDDED_SIGNUP_REDIRECT_URI")
        if not meta or not config_id or not config_id.isdigit() or not redirect_uri:
            return None
        return meta, config_id, redirect_uri

    @blueprint.post("/api/integrations/meta/whatsapp/authorize")
    @login_required
    def authorize_whatsapp():
        require_csrf()
        principal = principal_and_role()
        if principal is None:
            return jsonify({"error": "Business owner or administrator access is required."}), 403

        config = configuration()
        if config is None:
            return jsonify({"error": "Meta WhatsApp Embedded Signup is not configured."}), 503

        data = request.get_json(silent=True)
        if not isinstance(data, dict) or data.get("consent_confirmed") is not True:
            return jsonify({"error": "Explicit consent is required."}), 400

        meta, config_id, redirect_uri = config
        try:
            attempt = integration_service.create_oauth_attempt(
                business_id=principal.business_id,
                user_id=principal.user_id,
                provider=PROVIDER,
                redirect_uri=redirect_uri,
                consent_confirmed=True,
                ttl_seconds=600,
            )
        except (ValueError, PermissionError, RuntimeError):
            return jsonify({"error": "Could not start Meta authorisation."}), 400

        return jsonify({
            "provider": PROVIDER,
            "app_id": meta.app_id,
            "config_id": config_id,
            "graph_api_version": meta.graph_api_version,
            "redirect_uri": redirect_uri,
            "state": attempt["state"],
            "expires_at": attempt["expires_at"],
            "requested_access": sorted(SCOPES),
        }), 200

    @blueprint.post(CALLBACK_PATH)
    @login_required
    def complete_whatsapp_signup():
        require_csrf()
        principal = principal_and_role()
        if principal is None:
            return jsonify({"error": "Business owner or administrator access is required."}), 403

        config = configuration()
        if config is None:
            return jsonify({"error": "Meta WhatsApp Embedded Signup is not configured."}), 503

        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"error": "Invalid Meta callback data."}), 400

        state = data.get("state")
        if not isinstance(state, str):
            return jsonify({"error": "Meta authorisation could not be verified."}), 400

        meta, _, redirect_uri = config
        try:
            # Consume the one-time state before processing the callback.
            integration_service.consume_oauth_attempt(
                state=state,
                business_id=principal.business_id,
                user_id=principal.user_id,
                provider=PROVIDER,
                redirect_uri=redirect_uri,
            )
        except (ValueError, PermissionError, RuntimeError):
            return jsonify({"error": "Meta authorisation could not be verified."}), 400

        if data.get("error"):
            return jsonify({"error": "Meta authorisation was not completed."}), 400

        code = data.get("code")
        waba_id = data.get("waba_id")
        phone_number_id = data.get("phone_number_id")
        if (
            not isinstance(code, str) or not code.strip() or len(code) > 4096
            or not isinstance(waba_id, str) or not waba_id.isdigit()
            or not isinstance(phone_number_id, str) or not phone_number_id.isdigit()
        ):
            return jsonify({"error": "Meta signup returned incomplete asset information."}), 400

        saved = {}

        def persist_token(business_id, account_id, number_id, token):
            saved["connection_id"] = integration_service.connect(
                business_id=business_id,
                user_id=principal.user_id,
                provider=PROVIDER,
                external_account_id=account_id,
                scopes=set(SCOPES),
                secret_payload={
                    "access_token": token,
                    "waba_id": account_id,
                    "phone_number_id": number_id,
                },
                consent_confirmed=True,
            )

        try:
            signup = MetaEmbeddedSignupService(
                config=meta,
                persist_token=persist_token,
            )
            result = signup.complete_signup(
                business_id=principal.business_id,
                authorization_code=code,
                waba_id=waba_id,
                phone_number_id=phone_number_id,
            )
        except (MetaEmbeddedSignupError, ValueError, PermissionError, RuntimeError):
            return jsonify({"error": "Meta WhatsApp connection could not be verified or saved."}), 400

        connection_id = saved.get("connection_id")
        if not connection_id:
            return jsonify({"error": "Meta connection was not durably saved."}), 500

        return jsonify({
            "connected": True,
            "provider": PROVIDER,
            "connection_id": connection_id,
            "waba_id": result.waba_id,
            "phone_number_id": result.phone_number_id,
            "display_phone_number": result.display_phone_number,
            "verified_name": result.verified_name,
            "permissions": sorted(SCOPES),
            "sender_binding": "not_created",
        }), 200


    @blueprint.get("/integrations/whatsapp/connect")
    @login_required
    def whatsapp_signup_page():
        principal = principal_and_role()
        if principal is None:
            return jsonify({"error": "Business owner or administrator access is required."}), 403

        config = configuration()
        if config is None:
            return jsonify({"error": "Meta WhatsApp Embedded Signup is not configured."}), 503

        meta, config_id, _ = config
        signup_version = os.getenv("META_EMBEDDED_SIGNUP_VERSION", "v4").lower()
        if signup_version not in {"v4", "v5"}:
            return jsonify({"error": "Unsupported Embedded Signup version configuration."}), 503

        return render_template(
            "whatsapp_connect.html",
            meta_app_id=meta.app_id,
            config_id=config_id,
            graph_api_version=meta.graph_api_version,
            signup_version=signup_version,
        )

    return blueprint
