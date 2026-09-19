from __future__ import annotations

import os
from dataclasses import asdict
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
from app.founder.analytics import FounderAnalyticsService
from app.founder.operations import FounderOperationsService
from app.founder.safety_operations import FounderSafetyOperationsService
from app.persistence.founder_repository import SQLiteFounderRepository
from app.persistence.platform_event_repository import SQLitePlatformEventRepository
from app.persistence.safety_repository import SQLiteSafetyRepository
from app.persistence.safety_transaction import SQLiteSafetyTransaction
from app.safety.models import SafetyControlScope
from app.safety.service import SafetyControlError, SafetyControlService
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
    founders = SQLiteFounderRepository(db)

    auth_service = AuthenticationService(
        users=users,
        credentials=credentials,
        memberships=memberships,
        sessions=sessions,
        rate_limiter=SQLiteAuthenticationRateLimiter(db),
        founders=founders,
    )

    businesses = SQLiteBusinessRepository(db)
    access = BusinessAccessService(db)
    founder_access = FounderAuthorizationService(founders)
    founder_operations = FounderOperationsService(db)
    founder_analytics = FounderAnalyticsService(db)

    platform_events = SQLitePlatformEventRepository(db)
    safety_repository = SQLiteSafetyRepository(db)
    safety_service = SafetyControlService(
        safety_repository=safety_repository,
        founder_authorization=founder_access,
        platform_events=platform_events,
    )
    founder_safety_operations = FounderSafetyOperationsService(
        safety_repository=safety_repository,
        safety_service=safety_service,
        founder_authorization=founder_access,
    )

    builder = runtime_builder or _production_runtime_builder

    install_auth_hooks(app, auth_service)
    app.extensions["assistant_database"] = db
    app.extensions["assistant_businesses"] = businesses
    app.extensions["assistant_access"] = access
    app.extensions["assistant_founders"] = founders
    app.extensions["assistant_founder_access"] = founder_access
    app.extensions["assistant_founder_operations"] = founder_operations
    app.extensions["assistant_founder_analytics"] = founder_analytics
    app.extensions["assistant_safety_repository"] = safety_repository
    app.extensions["assistant_safety_service"] = safety_service
    app.extensions["assistant_founder_safety_operations"] = founder_safety_operations

    @app.errorhandler(BusinessAccessDenied)
    def access_denied(exc):
        return jsonify({"error": str(exc)}), 402

    @app.errorhandler(WebSecurityError)
    def web_security_error(exc):
        return jsonify({"error": str(exc)}), 403

    @app.errorhandler(FounderAccessDenied)
    def founder_access_denied(exc):
        return jsonify({"error": str(exc)}), 403

    @app.errorhandler(SafetyControlError)
    def safety_control_error(exc):
        if request.path.startswith("/api/"):
            return jsonify({"error": str(exc)}), 400
        return "Bad request", 400

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
        return render_template("founder.html")


    @app.get("/api/founder/businesses")
    @login_required
    def founder_businesses_api():
        founder_access.require_founder(g.principal)

        limit = _query_limit(
            request.args.get("limit"),
            default=FounderOperationsService.MAX_BUSINESSES,
            maximum=FounderOperationsService.MAX_BUSINESSES,
        )

        businesses_view = founder_operations.list_businesses(limit)

        return jsonify(
            {
                "businesses": [
                    business.as_dict()
                    for business in businesses_view
                ]
            }
        )


    @app.get("/api/founder/businesses/<business_id>")
    @login_required
    def founder_business_api(business_id: str):
        founder_access.require_founder(g.principal)

        business = founder_operations.get_business(business_id)

        if business is None:
            return jsonify({"error": "Business not found."}), 404

        return jsonify(business.as_dict())


    @app.get("/api/founder/analytics")
    @login_required
    def founder_analytics_api():
        founder_access.require_founder(g.principal)
        analytics = founder_analytics.summary()
        return jsonify(asdict(analytics))

    @app.get("/api/founder/events")
    @login_required
    def founder_events_api():
        founder_access.require_founder(g.principal)

        business_id = request.args.get("business_id")

        if business_id is not None and not business_id.strip():
            raise ValueError("business_id must be a non-empty string.")

        if business_id is not None:
            if businesses.get(business_id) is None:
                return jsonify({"error": "Business not found."}), 404

        limit = _query_limit(
            request.args.get("limit"),
            default=FounderOperationsService.MAX_EVENTS,
            maximum=FounderOperationsService.MAX_EVENTS,
        )

        return jsonify(
            {
                "events": founder_operations.recent_events(
                    business_id=business_id,
                    limit=limit,
                )
            }
        )

    # ------------------------------------------------------------------
    # Founder safety control plane
    #
    # These routes are intentionally thin. They authenticate the Founder,
    # validate transport input, and delegate all safety lifecycle mutation
    # to FounderSafetyOperationsService.
    # ------------------------------------------------------------------

    @app.get("/api/founder/safety/controls")
    @login_required
    def founder_safety_controls_api():
        founder_access.require_founder(g.principal)

        limit = _query_limit(
            request.args.get("limit"),
            default=FounderSafetyOperationsService.MAX_CONTROLS,
            maximum=FounderSafetyOperationsService.MAX_CONTROLS,
        )

        controls = founder_safety_operations.list_active_controls(
            g.principal,
            limit=limit,
        )

        return jsonify(
            {
                "controls": [
                    control.as_dict()
                    if hasattr(control, "as_dict")
                    else {
                        "control_id": control.control_id,
                        "scope": control.scope.value,
                        "target": control.target,
                        "state": control.state.value,
                        "reason": control.reason,
                        "activated_at": control.activated_at.isoformat(),
                        "activated_by_user_id": control.activated_by_user_id,
                        "incident_id": control.incident_id,
                        "resolved_at": (
                            control.resolved_at.isoformat()
                            if control.resolved_at is not None
                            else None
                        ),
                        "resolved_by_user_id": control.resolved_by_user_id,
                        "resumed_at": (
                            control.resumed_at.isoformat()
                            if control.resumed_at is not None
                            else None
                        ),
                        "resumed_by_user_id": control.resumed_by_user_id,
                    }
                    for control in controls
                ]
            }
        )

    @app.get("/api/founder/safety/controls/<control_id>")
    @login_required
    def founder_safety_control_api(control_id: str):
        founder_access.require_founder(g.principal)

        control = founder_safety_operations.get_control(
            g.principal,
            control_id,
        )

        if control is None:
            return jsonify({"error": "Safety control not found."}), 404

        return jsonify(
            control.as_dict()
            if hasattr(control, "as_dict")
            else {
                "control_id": control.control_id,
                "scope": control.scope.value,
                "target": control.target,
                "state": control.state.value,
                "reason": control.reason,
                "activated_at": control.activated_at.isoformat(),
                "activated_by_user_id": control.activated_by_user_id,
                "incident_id": control.incident_id,
                "resolved_at": (
                    control.resolved_at.isoformat()
                    if control.resolved_at is not None
                    else None
                ),
                "resolved_by_user_id": control.resolved_by_user_id,
                "resumed_at": (
                    control.resumed_at.isoformat()
                    if control.resumed_at is not None
                    else None
                ),
                "resumed_by_user_id": control.resumed_by_user_id,
            }
        )

    @app.get("/api/founder/safety/incidents/<incident_id>")
    @login_required
    def founder_safety_incident_api(incident_id: str):
        founder_access.require_founder(g.principal)

        incident = founder_safety_operations.get_incident(
            g.principal,
            incident_id,
        )

        if incident is None:
            return jsonify({"error": "Safety incident not found."}), 404

        return jsonify(
            incident.as_dict()
            if hasattr(incident, "as_dict")
            else {
                "incident_id": incident.incident_id,
                "status": incident.status.value,
                "reason": incident.reason,
                "created_at": incident.created_at.isoformat(),
                "created_by_user_id": incident.created_by_user_id,
                "resolved_at": (
                    incident.resolved_at.isoformat()
                    if incident.resolved_at is not None
                    else None
                ),
                "resolved_by_user_id": incident.resolved_by_user_id,
                "verification_notes": incident.verification_notes,
                "verified_at": (
                    incident.verified_at.isoformat()
                    if incident.verified_at is not None
                    else None
                ),
                "verified_by_user_id": incident.verified_by_user_id,
                "resume_authorized_at": (
                    incident.resume_authorized_at.isoformat()
                    if incident.resume_authorized_at is not None
                    else None
                ),
                "resume_authorized_by_user_id": (
                    incident.resume_authorized_by_user_id
                ),
                "closed_at": (
                    incident.closed_at.isoformat()
                    if incident.closed_at is not None
                    else None
                ),
                "closed_by_user_id": incident.closed_by_user_id,
            }
        )

    @app.post("/api/founder/safety/controls/halt")
    @login_required
    def founder_safety_halt_api():
        require_csrf(request)
        founder_access.require_founder(g.principal)

        data = _json_object()

        scope_value = data.get("scope")
        target = data.get("target")
        reason = data.get("reason")
        incident_id = data.get("incident_id")

        if not isinstance(scope_value, str) or not scope_value.strip():
            raise ValueError("scope must be a non-empty string.")

        try:
            scope = SafetyControlScope(scope_value.strip().lower())
        except ValueError as exc:
            raise ValueError("scope must be a valid safety control scope.") from exc

        result = founder_safety_operations.halt(
            g.principal,
            scope=scope,
            target=target,
            reason=reason,
            incident_id=incident_id,
        )

        return jsonify(
            result.as_dict()
            if hasattr(result, "as_dict")
            else {
                "control_id": result.control_id,
                "scope": result.scope.value,
                "target": result.target,
                "state": result.state.value,
                "reason": result.reason,
                "activated_at": result.activated_at.isoformat(),
                "activated_by_user_id": result.activated_by_user_id,
                "incident_id": result.incident_id,
            }
        ), 201

    @app.post("/api/founder/safety/incidents/<incident_id>/investigate")
    @login_required
    def founder_safety_investigate_api(incident_id: str):
        require_csrf(request)
        founder_access.require_founder(g.principal)

        incident = founder_safety_operations.begin_investigation(
            g.principal,
            incident_id,
        )

        return jsonify(
            incident.as_dict()
            if hasattr(incident, "as_dict")
            else {
                "incident_id": incident.incident_id,
                "status": incident.status.value,
            }
        )

    @app.post("/api/founder/safety/incidents/<incident_id>/resolve")
    @login_required
    def founder_safety_resolve_api(incident_id: str):
        require_csrf(request)
        founder_access.require_founder(g.principal)

        data = _json_object()

        incident = founder_safety_operations.resolve_incident(
            g.principal,
            incident_id,
            notes=data.get("notes"),
        )

        return jsonify(
            incident.as_dict()
            if hasattr(incident, "as_dict")
            else {
                "incident_id": incident.incident_id,
                "status": incident.status.value,
            }
        )

    @app.post("/api/founder/safety/incidents/<incident_id>/verify")
    @login_required
    def founder_safety_verify_api(incident_id: str):
        require_csrf(request)
        founder_access.require_founder(g.principal)

        data = _json_object()

        incident = founder_safety_operations.verify_fix(
            g.principal,
            incident_id,
            notes=data.get("notes"),
        )

        return jsonify(
            incident.as_dict()
            if hasattr(incident, "as_dict")
            else {
                "incident_id": incident.incident_id,
                "status": incident.status.value,
            }
        )

    @app.post(
        "/api/founder/safety/incidents/<incident_id>/authorize-resume"
    )
    @login_required
    def founder_safety_authorize_resume_api(incident_id: str):
        require_csrf(request)
        founder_access.require_founder(g.principal)

        incident = founder_safety_operations.authorize_resume(
            g.principal,
            incident_id,
        )

        return jsonify(
            incident.as_dict()
            if hasattr(incident, "as_dict")
            else {
                "incident_id": incident.incident_id,
                "status": incident.status.value,
            }
        )

    @app.post("/api/founder/safety/controls/<control_id>/resume")
    @login_required
    def founder_safety_resume_control_api(control_id: str):
        require_csrf(request)
        founder_access.require_founder(g.principal)

        control = founder_safety_operations.resume_control(
            g.principal,
            control_id,
        )

        return jsonify(
            control.as_dict()
            if hasattr(control, "as_dict")
            else {
                "control_id": control.control_id,
                "scope": control.scope.value,
                "target": control.target,
                "state": control.state.value,
                "incident_id": control.incident_id,
                "resumed_at": (
                    control.resumed_at.isoformat()
                    if control.resumed_at is not None
                    else None
                ),
                "resumed_by_user_id": control.resumed_by_user_id,
            }
        )

    @app.post("/api/founder/safety/incidents/<incident_id>/close")
    @login_required
    def founder_safety_close_api(incident_id: str):
        require_csrf(request)
        founder_access.require_founder(g.principal)

        incident = founder_safety_operations.close_incident(
            g.principal,
            incident_id,
        )

        return jsonify(
            incident.as_dict()
            if hasattr(incident, "as_dict")
            else {
                "incident_id": incident.incident_id,
                "status": incident.status.value,
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

    @app.post("/api/auth/founder/login")
    def founder_login_api():
        require_csrf(request)
        data = _json_object()
        try:
            principal = auth_service.login_founder(
                _required(data, "email"),
                _required(data, "password"),
                source_key="founder-web",
            )
        except AuthenticationError:
            return jsonify({"error": "Authentication failed."}), 401

        return set_session_cookie(
            jsonify({
                "message": "Founder signed in.",
                "scope": principal.scope.value,
            }),
            principal.session_id,
        )

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
        result = builder(business).handle(
            AssistantMessage(business.business_id, text),
            channel="web",
        )
        if not isinstance(result, AssistantResponse):
            return jsonify({"error": "Assistant returned an invalid response."}), 500
        return jsonify({"assistant_name": result.assistant_name, "message": result.message, "should_speak": result.should_speak})

    return app


def _production_runtime_builder(business: Business) -> OrchestratorLike:
    from app.cli.assistant_factory import build_orchestrator_for_business
    return build_orchestrator_for_business(business)


def _query_limit(
    value: str | None,
    *,
    default: int,
    maximum: int,
) -> int:
    if value is None:
        return default

    if not value.strip():
        raise ValueError("limit must be a positive integer.")

    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(
            "limit must be a positive integer."
        ) from exc

    if parsed < 1 or parsed > maximum:
        raise ValueError(
            f"limit must be between 1 and {maximum}."
        )

    return parsed


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
