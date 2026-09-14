from __future__ import annotations

import os
from typing import Callable, Protocol

from flask import Flask, jsonify, redirect, render_template, request, url_for, g

from app.assistant.message import AssistantMessage
from app.assistant.response import AssistantResponse
from app.auth.errors import AuthenticationError, BusinessSelectionRequired
from app.auth.service import AuthenticationService
from app.auth.signup import SQLiteSignupTransaction, SignupConflict
from app.identity.models import UserRole
from app.models.business import Business
from app.models.voice import SUPPORTED_VOICES
from app.persistence.business_repository import SQLiteBusinessRepository
from app.persistence.credential_repository import SQLiteCredentialRepository
from app.persistence.database import SQLiteDatabase
from app.persistence.membership_repository import SQLiteMembershipRepository
from app.persistence.session import SQLiteSessionRepository
from app.persistence.user_repository import SQLiteUserRepository
from app.auth.rate_limit import SQLiteAuthenticationRateLimiter
from app.founder.authorization import FounderAccessDenied, FounderAuthorizationService
from app.persistence.founder_repository import SQLiteFounderRepository
from app.web.access import BusinessAccessDenied, BusinessAccessService
from app.web.auth import SESSION_COOKIE, clear_session_cookie, install_auth_hooks, issue_csrf_cookie, login_required, require_csrf, set_session_cookie
from app.web.security import WebSecurityError


class OrchestratorLike(Protocol):
    def handle(self, message: AssistantMessage, confirmed: bool = False): ...


RuntimeBuilder = Callable[[Business], OrchestratorLike]


def create_app(*, database: SQLiteDatabase | None = None, runtime_builder: RuntimeBuilder | None = None, testing: bool = False) -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.update(TESTING=testing, MAX_CONTENT_LENGTH=64 * 1024, JSON_SORT_KEYS=False)

    db = database or SQLiteDatabase(os.getenv("ASSISTANT_DB_PATH", "data/assistant.sqlite3"))
    db.initialize()

    users = SQLiteUserRepository(db)
    credentials = SQLiteCredentialRepository(db)
    memberships = SQLiteMembershipRepository(db)
    sessions = SQLiteSessionRepository(db)
    auth_service = AuthenticationService(
        users=users,
        credentials=credentials,
        memberships=memberships,
        sessions=sessions,
        rate_limiter=SQLiteAuthenticationRateLimiter(db),
    )
    businesses = SQLiteBusinessRepository(db)
    access = BusinessAccessService(db)
    founders = SQLiteFounderRepository(db)
    founder_access = FounderAuthorizationService(founders)
    builder = runtime_builder or _production_runtime_builder

    install_auth_hooks(app, auth_service)
    app.extensions["assistant_database"] = db
    app.extensions["assistant_businesses"] = businesses
    app.extensions["assistant_access"] = access
    app.extensions["assistant_founders"] = founders
    app.extensions["assistant_founder_access"] = founder_access

    @app.errorhandler(BusinessAccessDenied)
    def access_denied(exc):
        return jsonify({"error": str(exc)}), 402

    @app.errorhandler(WebSecurityError)
    def web_security_error(exc):
        return jsonify({"error": str(exc)}), 403

    @app.errorhandler(FounderAccessDenied)
    def founder_access_denied(exc):
        return jsonify({"error": str(exc)}), 403

    @app.errorhandler(PermissionError)
    def permission_error(exc):
        return jsonify({"error": str(exc)}), 403

    @app.errorhandler(ValueError)
    def value_error(exc):
        if request.path.startswith("/api/"):
            return jsonify({"error": str(exc)}), 400
        return "Bad request", 400

    @app.get("/")
    def index():
        return redirect(url_for("dashboard_page" if g.principal else "login_page"))

    @app.get("/login")
    def login_page():
        return issue_csrf_cookie(app.make_response(render_template("login.html")))

    @app.get("/signup")
    def signup_page():
        return issue_csrf_cookie(app.make_response(render_template("signup.html", voices=sorted(SUPPORTED_VOICES))))

    @app.get("/founder")
    @login_required
    def founder_dashboard_page():
        founder_access.require_founder(g.principal)

        return jsonify(
            {
                "message": "Founder Operations boundary active.",
                "user_id": g.principal.user_id,
            }
        )

    @app.get("/dashboard")
    @login_required
    def dashboard_page():
        business = businesses.get(g.principal.business_id)
        if business is None:
            return jsonify({"error": "Business not found."}), 404
        return render_template("dashboard.html", business=business, principal=g.principal, access=access.resolve(business.business_id))

    @app.post("/api/auth/signup")
    def signup_api():
        require_csrf(request)
        data = _json_object()
        try:
            user, business, _, _ = SQLiteSignupTransaction(db).signup(
                display_name=_required(data, "display_name"), email=_required(data, "email"), password=_required(data, "password"),
                business_name=_required(data, "business_name"), assistant_name=_required(data, "assistant_name"),
                assistant_voice=_required(data, "assistant_voice").lower(),
            )
        except SignupConflict as exc:
            return jsonify({"error": str(exc)}), 409
        return jsonify({"user_id": user.user_id, "business_id": business.business_id, "message": "Account created. Sign in to continue."}), 201

    @app.post("/api/auth/login")
    def login_api():
        require_csrf(request)
        data = _json_object()
        try:
            principal = auth_service.login(_required(data, "email"), _required(data, "password"), source_key="web")
        except BusinessSelectionRequired as exc:
            return jsonify({"error": "Business selection is required.", "businesses": [{"business_id": x[0], "name": x[1], "role": x[2]} for x in exc.memberships]}), 409
        except AuthenticationError:
            return jsonify({"error": "Authentication failed."}), 401
        return set_session_cookie(jsonify({"message": "Signed in.", "business_id": principal.business_id}), principal.session_id)

    @app.post("/api/auth/logout")
    @login_required
    def logout_api():
        require_csrf(request)
        token = request.cookies.get(SESSION_COOKIE)
        if token:
            auth_service.logout(token)
        return clear_session_cookie(jsonify({"message": "Signed out."}))

    @app.get("/api/me")
    @login_required
    def me_api():
        business = businesses.get(g.principal.business_id)
        if business is None:
            return jsonify({"error": "Business not found."}), 404
        business_access = access.resolve(business.business_id)
        return jsonify({"user_id": g.principal.user_id, "business_id": business.business_id, "role": g.principal.role.value, "business": {"name": business.name, "owner_name": business.owner_name, "assistant_name": business.assistant_name, "assistant_voice": business.assistant_voice}, "commercial": {"status": business_access.status.value, "allowed": business_access.allowed, "reason": business_access.reason, "trial_ends_at": business_access.trial_ends_at.isoformat() if business_access.trial_ends_at else None}})

    @app.post("/api/business/config")
    @login_required
    def update_business_config():
        require_csrf(request)
        if g.principal.role != UserRole.OWNER:
            return jsonify({"error": "Only the business owner may change assistant configuration."}), 403
        current = businesses.get(g.principal.business_id)
        if current is None:
            return jsonify({"error": "Business not found."}), 404
        data = _json_object()
        assistant_name = _required(data, "assistant_name")
        assistant_voice = _required(data, "assistant_voice").lower()
        if assistant_voice not in SUPPORTED_VOICES:
            return jsonify({"error": "Unsupported assistant voice."}), 400
        updated = Business(current.business_id, current.name, current.owner_name, assistant_name, assistant_voice)
        businesses.save(updated)
        return jsonify({"assistant_name": updated.assistant_name, "assistant_voice": updated.assistant_voice})

    @app.post("/api/assistant/message")
    @login_required
    def assistant_message_api():
        require_csrf(request)
        business = businesses.get(g.principal.business_id)
        if business is None:
            return jsonify({"error": "Business not found."}), 404
        access.require_execution(business.business_id)
        data = _json_object()
        text = _required(data, "message")
        if len(text) > 8000:
            return jsonify({"error": "Message is too long."}), 400
        result = builder(business).handle(AssistantMessage(business.business_id, text))
        if not isinstance(result, AssistantResponse):
            return jsonify({"error": "Assistant returned an invalid response."}), 500
        return jsonify({"assistant_name": result.assistant_name, "message": result.message, "should_speak": result.should_speak})

    return app


def _production_runtime_builder(business: Business) -> OrchestratorLike:
    from app.cli.assistant_factory import build_orchestrator_for_business
    return build_orchestrator_for_business(business)


def _json_object() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValueError("Request body must be a JSON object.")
    return data


def _required(data: dict, field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string.")
    return value.strip()
