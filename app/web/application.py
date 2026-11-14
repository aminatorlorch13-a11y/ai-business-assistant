from __future__ import annotations

from flask import current_app
import atexit
import threading

import base64
import os
from datetime import datetime, timezone
from dataclasses import asdict
from typing import Callable, Protocol

from flask import Flask, jsonify, redirect, render_template, request, url_for, g

from app.assistant.message import AssistantMessage
from app.assistant.conversation import ConversationHistory
from app.assistant.response import AssistantResponse
from app.assistant.orchestrator import AssistantOrchestrator
from app.assistant.structured_processor import StructuredAssistantProcessor
from app.ai.errors import AIProviderError
from app.ai.groq_config import GroqConfig
from app.ai.groq_provider import GroqHTTPProvider
from app.ai.structured_provider import ParsedRawAIProvider
from app.identity.tenant import TenantContext
from app.memory.context import MemoryContextBuilder
from app.persistence.capability_confirmation import (
    SQLiteCapabilityConfirmationRepository,
)
from app.assistant.capability_confirmation_service import (
    CapabilityConfirmationService,
)
from app.assistant.capability_composition import (
    build_production_capability_composition,
)
from app.auth.errors import AuthenticationError, BusinessSelectionRequired
from app.auth.service import AuthenticationService
from app.auth.signup import SQLiteSignupTransaction, SignupConflict
from app.identity.models import UserRole
from app.models.business import Business
from app.models.voice import SUPPORTED_VOICES
from app.voice.elevenlabs_engine import ElevenLabsConfig, ElevenLabsSpeechEngine
from app.voice.request import SpeechRequest
from app.persistence.business_repository import SQLiteBusinessRepository
from app.persistence.credential_repository import SQLiteCredentialRepository
from app.persistence.database import SQLiteDatabase
from app.persistence.web_conversation import SQLiteWebConversationRepository
from app.persistence.membership_repository import SQLiteMembershipRepository
from app.owner.repository import SQLiteOwnerLifestyleRepository
from app.owner.attention_events import SQLiteAttentionEventRepository
from app.owner.service import OwnerLifestyleService
from app.owner.attention_service import OwnerAttentionService

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
from app.integrations.security import FernetSecretCipher
from app.integrations.service import IntegrationService
from app.persistence.integration_repository import SQLiteIntegrationRepository
from app.persistence.subscription_repository import SQLiteSubscriptionRepository
from app.persistence.communication_repository import SQLiteCommunicationRepository
from app.owner.communication_service import OwnerCommunicationService
from app.owner.communication_worker import CommunicationDeliveryWorker
from app.whatsapp.provisioning_verifier import MetaWhatsAppIdentityProvisioningVerifier
from app.web.google_oauth import create_google_oauth_blueprint
from app.web.meta_whatsapp_signup import create_meta_whatsapp_signup_blueprint
from app.whatsapp.config import MetaWhatsAppConfig
from app.whatsapp.meta_cloud_provider import MetaWhatsAppCloudProvider
from app.whatsapp.identity import WhatsAppIdentityResolver
from app.whatsapp.binding_service import WhatsAppBindingService
from app.whatsapp.service import WhatsAppChannelService
from app.whatsapp.webhook import create_meta_whatsapp_blueprint
from app.persistence.whatsapp import SQLiteWhatsAppRepository
from app.persistence.whatsapp_conversation import SQLiteWhatsAppConversationRepository



class OrchestratorLike(Protocol):
    def handle(
        self,
        message: AssistantMessage,
        confirmed: bool = False,
        *,
        tenant: TenantContext | None = None,
        conversation_history: ConversationHistory | None = None,
        channel: str | None = None,
        integration: str | None = None,
    ) -> AssistantResponse: ...


RuntimeBuilder = Callable[[Business], OrchestratorLike]

class SpeechSynthesizer(Protocol):
    def synthesize(self, speech_request: SpeechRequest) -> bytes: ...


def create_app(
    *,
    database: SQLiteDatabase | None = None,
    runtime_builder: RuntimeBuilder | None = None,
    speech_synthesizer: SpeechSynthesizer | None = None,
    testing: bool = False,
    endpoint_verifier=None,
    identity_verifier=None,
) -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.update(TESTING=testing, MAX_CONTENT_LENGTH=64 * 1024, JSON_SORT_KEYS=False)

    db = database or SQLiteDatabase(os.getenv("ASSISTANT_DB_PATH", "data/assistant.sqlite3"))
    db.initialize()
    web_conversations = SQLiteWebConversationRepository(db)

    users = SQLiteUserRepository(db)
    credentials = SQLiteCredentialRepository(db)
    memberships = SQLiteMembershipRepository(db)
    owner_lifestyle_repository = SQLiteOwnerLifestyleRepository(db)
    owner_lifestyle_service = OwnerLifestyleService(
        owner_lifestyle_repository, memberships
    )
    attention_event_repository = SQLiteAttentionEventRepository(db)
    owner_attention_service = OwnerAttentionService(
        owner_lifestyle_service, attention_event_repository
    )
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
    subscriptions = SQLiteSubscriptionRepository(db)
    app.extensions['assistant_subscription_repository'] = subscriptions
    access = BusinessAccessService(db)

    # WhatsApp remains disabled until every real Meta credential is configured.
    whatsapp_config = MetaWhatsAppConfig.from_environment()
    if whatsapp_config is not None:
        whatsapp_repository = SQLiteWhatsAppRepository(db)
        def authorize_whatsapp_binding(user_id, business_id):
            membership = memberships.get(user_id, business_id)
            if membership is None:
                return None
            return membership.role

        whatsapp_binding_service = WhatsAppBindingService(
            repository=whatsapp_repository,
            sender_hash_secret=whatsapp_config.sender_hash_secret,
            authorize_business_admin=authorize_whatsapp_binding,
            # Deliberately unset until tenant-specific Meta ownership
            # verification is implemented. Registration fails closed.
            verify_provider_account=None,
        )
        app.extensions["assistant_whatsapp_binding_service"] = (
            whatsapp_binding_service
        )
        whatsapp_conversations = SQLiteWhatsAppConversationRepository(db)
        whatsapp_identity = WhatsAppIdentityResolver(
            repository=whatsapp_repository,
            membership_repository=memberships,
            sender_hash_secret=whatsapp_config.sender_hash_secret,
        )
        whatsapp_provider = MetaWhatsAppCloudProvider(
            access_token=whatsapp_config.access_token,
            graph_api_version=whatsapp_config.graph_api_version,
        )

        def whatsapp_orchestrator_factory(tenant):
            business = businesses.get(tenant.business_id)
            if business is None:
                raise LookupError("The WhatsApp business no longer exists.")

            if runtime_builder is not None:
                return runtime_builder(business)

            return _production_runtime_builder(business, database=db)

        whatsapp_service = WhatsAppChannelService(
            repository=whatsapp_repository,
            identity_resolver=whatsapp_identity,
            business_access=access,
            orchestrator_factory=whatsapp_orchestrator_factory,
            provider=whatsapp_provider,
            conversation_repository=whatsapp_conversations,
            sender_hash_secret=whatsapp_config.sender_hash_secret,
        )

        app.register_blueprint(
            create_meta_whatsapp_blueprint(
                service=whatsapp_service,
                config=whatsapp_config,
            )
        )

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

    integration_service = None
    try:
        integration_cipher = FernetSecretCipher.from_environment()
        integration_service = IntegrationService(
            SQLiteIntegrationRepository(db),
            integration_cipher,
        )
    except (RuntimeError, ValueError):
        # Keep the main application available; integration routes fail closed.
        integration_service = None

    communication_repository = SQLiteCommunicationRepository(db)
    if whatsapp_config is not None and identity_verifier is None:
        identity_verifier = MetaWhatsAppIdentityProvisioningVerifier(
            access_token=whatsapp_config.access_token,
            graph_api_version=whatsapp_config.graph_api_version,
        )

    communication_service = None
    configured_whatsapp_provider = locals().get("whatsapp_provider")
    can_use_whatsapp_verification = (
        whatsapp_config is not None and configured_whatsapp_provider is not None
    )
    has_legacy_verification = (
        endpoint_verifier is not None and identity_verifier is not None
    )

    if can_use_whatsapp_verification or has_legacy_verification:
        communication_cipher = FernetSecretCipher.from_environment()
        communication_service = OwnerCommunicationService(
            repository=communication_repository,
            cipher=communication_cipher,
            lifestyle_service=owner_lifestyle_service,
            endpoint_verifier=endpoint_verifier,
            identity_verifier=identity_verifier,
            whatsapp_provider=configured_whatsapp_provider,
            sender_hash_secret=(
                whatsapp_config.sender_hash_secret
                if whatsapp_config is not None else None
            ),
        )

    app.extensions["assistant_communication"] = communication_service

    communication_worker = None
    configured_whatsapp_provider = locals().get("whatsapp_provider")

    if communication_service is not None and configured_whatsapp_provider is not None:
        communication_worker = CommunicationDeliveryWorker(
            repository=communication_repository,
            communication_service=communication_service,
            provider=configured_whatsapp_provider,
        )
        communication_worker.start()
        atexit.register(communication_worker.stop)

    app.extensions["assistant_communication_worker"] = communication_worker
    app.extensions["assistant_communication_repository"] = communication_repository

    app.extensions["assistant_integrations"] = integration_service
    app.register_blueprint(create_google_oauth_blueprint(
        integration_service=integration_service,
        memberships=memberships,
        client_id=os.getenv("GOOGLE_CLIENT_ID"),
        client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
        redirect_uri=os.getenv("GOOGLE_GMAIL_REDIRECT_URI"),
    ))
    app.register_blueprint(create_meta_whatsapp_signup_blueprint(
        integration_service=integration_service,
        memberships=memberships,
    ))
    app.extensions["assistant_owner_lifestyle"] = owner_lifestyle_service
    app.extensions["assistant_owner_attention"] = owner_attention_service
    app.extensions["assistant_attention_events"] = attention_event_repository
    app.extensions["assistant_database"] = db
    app.extensions["assistant_web_conversations"] = web_conversations
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

    def _forge_terminal_composition():
        composition = app.extensions.get("assistant_capability_composition")
        if composition is None:
            composition = build_production_capability_composition(
        integration_service=current_app.extensions.get("assistant_integrations"),
                database=app.extensions["assistant_database"],
            )
            app.extensions["assistant_capability_composition"] = composition
        return composition

    def _forge_terminal_service():
        service = app.extensions.get("assistant_forge_terminal_service")
        if service is not None:
            return service

        # Runner configuration is needed only when a terminal is opened.
        composition = _forge_terminal_composition()
        service = composition.create_forge_terminal_service()
        app.extensions["assistant_forge_terminal_service"] = service
        return service

    def _forge_terminal_identity():
        business_id = getattr(g.principal, "business_id", None)
        if not business_id:
            raise PermissionError("An active business is required.")

        business = businesses.get(business_id)
        if business is None:
            raise PermissionError("The active business is unavailable.")

        access.require_execution(business_id)
        return business_id

    @app.get("/api/forge/terminal/projects")
    @login_required
    def forge_terminal_projects():
        business_id = _forge_terminal_identity()

        # Project discovery must not depend on remote runner configuration.
        composition = _forge_terminal_composition()
        if composition is None or composition.forge_job_store is None:
            return jsonify({"error": "Forge job storage is unavailable."}), 503

        database = app.extensions["assistant_database"]
        with database.connection() as connection:
            rows = connection.execute(
                """
                SELECT project_id, name
                FROM forge_projects
                WHERE business_id = ? AND status = 'ACTIVE'
                ORDER BY name ASC, project_id ASC
                LIMIT 100
                """,
                (business_id,),
            ).fetchall()

        projects = []
        for row in rows:
            project_id = row["project_id"]
            records = composition.forge_job_store.list_for_project(
                business_id, project_id
            )
            jobs = []

            for record in records:
                job = record.job
                status = getattr(job.status, "value", job.status)

                # Locked candidates and all non-vaulted jobs stay unavailable.
                if status != "completed_vaulted":
                    continue

                job_type = getattr(job.job_type, "value", job.job_type)
                phase = getattr(job.phase, "value", job.phase)
                created_at = job.created_at
                if hasattr(created_at, "isoformat"):
                    created_at = created_at.isoformat()

                jobs.append({
                    "job_id": job.job_id,
                    "job_type": str(job_type),
                    "phase": str(phase),
                    "created_at": str(created_at),
                })

                if len(jobs) >= 50:
                    break

            projects.append({
                "project_id": project_id,
                "name": row["name"],
                "jobs": jobs,
            })

        return jsonify({"ok": True, "projects": projects}), 200

    @app.post("/api/forge/projects/<project_id>/jobs/<job_id>/terminal")
    @login_required
    def forge_terminal_open(project_id: str, job_id: str):
        require_csrf(request)
        business_id = _forge_terminal_identity()
        service = _forge_terminal_service()
        result = service.open_session(business_id, project_id, job_id)
        return jsonify({"ok": True, "terminal": result}), 200

    @app.post("/api/forge/projects/<project_id>/jobs/<job_id>/terminal/command")
    @login_required
    def forge_terminal_command(project_id: str, job_id: str):
        require_csrf(request)
        business_id = _forge_terminal_identity()
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            raise ValueError("A JSON request body is required.")

        command = payload.get("command")
        if not isinstance(command, str) or not command.strip():
            raise ValueError("A non-empty terminal command is required.")
        if len(command) > 4096:
            raise ValueError("Terminal commands cannot exceed 4096 characters.")

        service = _forge_terminal_service()
        result = service.execute(business_id, project_id, job_id, command)
        return jsonify(result), 200

    @app.post("/api/forge/projects/<project_id>/jobs/<job_id>/terminal/save")
    @login_required
    def forge_terminal_save(project_id: str, job_id: str):
        require_csrf(request)
        business_id = _forge_terminal_identity()
        service = _forge_terminal_service()
        result = service.save_session(business_id, project_id, job_id)
        return jsonify({"ok": True, "result": result}), 200

    @app.delete("/api/forge/projects/<project_id>/jobs/<job_id>/terminal")
    @login_required
    def forge_terminal_close(project_id: str, job_id: str):
        require_csrf(request)
        business_id = _forge_terminal_identity()
        service = _forge_terminal_service()
        closed = service.close_session(business_id, project_id, job_id)
        return jsonify({"ok": True, "closed": closed}), 200

    @app.get("/")
    def index():
        if g.principal:
            return redirect(url_for("dashboard_page"))
        return render_template("landing.html")

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


    def require_owner_lifestyle_access():
        if g.principal.role != UserRole.OWNER:
            return jsonify({"error": "Only the business owner may access lifestyle settings."}), 403
        return None

    @app.post("/api/owner/communication/whatsapp/verify")
    @login_required
    def owner_whatsapp_verify():
        require_csrf(request)
        denied = require_owner_lifestyle_access()
        if denied:
            return denied

        service = app.extensions.get("assistant_communication")
        if service is None:
            return jsonify({"error": "WhatsApp verification is not configured."}), 503

        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"error": "A JSON request body is required."}), 400

        endpoint = data.get("endpoint")
        consent = data.get("consent_granted")
        if not isinstance(endpoint, str) or type(consent) is not bool:
            return jsonify({"error": "A phone number and explicit consent are required."}), 400
        if consent is not True:
            return jsonify({"error": "Explicit consent is required."}), 403

        try:
            result = service.begin_whatsapp_endpoint_verification(
                g.principal,
                g.principal.business_id,
                endpoint=endpoint,
                consent_granted=consent,
            )
            return jsonify(result), 202
        except PermissionError as exc:
            return jsonify({"error": str(exc)}), 403
        except (ValueError, TypeError) as exc:
            return jsonify({"error": str(exc)}), 400
        except RuntimeError:
            return jsonify({"error": "WhatsApp verification could not be started."}), 503

    @app.get("/api/owner/lifestyle")
    @login_required
    def owner_lifestyle_get():
        denied = require_owner_lifestyle_access()
        if denied:
            return denied
        try:
            from dataclasses import asdict
            preferences = owner_lifestyle_service.get_preferences(
                g.principal, g.principal.business_id
            )
            return jsonify(asdict(preferences))
        except PermissionError:
            return jsonify({"error": "Owner access denied."}), 403

    @app.put("/api/owner/lifestyle")
    @login_required
    def owner_lifestyle_update():
        require_csrf(request)
        denied = require_owner_lifestyle_access()
        if denied:
            return denied
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or not isinstance(data.get("changes"), dict):
            return jsonify({"error": "Expected a JSON object containing changes."}), 400
        try:
            from dataclasses import asdict
            preferences = owner_lifestyle_service.update_preferences(
                g.principal, g.principal.business_id, data["changes"]
            )
            return jsonify(asdict(preferences))
        except (ValueError, TypeError) as exc:
            return jsonify({"error": str(exc)}), 400
        except PermissionError:
            return jsonify({"error": "Owner access denied."}), 403

    @app.post("/api/owner/attention/events")
    @login_required
    def owner_attention_ingest():
        require_csrf(request)
        denied = require_owner_lifestyle_access()
        if denied:
            return denied

        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"error": "Expected a JSON object."}), 400

        allowed_fields = {
            "idempotency_key", "event_type", "severity",
            "title", "details", "payload",
        }
        if set(data) - allowed_fields:
            return jsonify({"error": "Unsupported event fields."}), 400

        required_fields = (
            "idempotency_key", "event_type", "severity", "title",
        )
        if any(field not in data for field in required_fields):
            return jsonify({"error": "Missing required event fields."}), 400

        try:
            from dataclasses import asdict

            event = owner_attention_service.ingest(
                g.principal,
                g.principal.business_id,
                idempotency_key=data["idempotency_key"],
                event_type=data["event_type"],
                severity=data["severity"],
                title=data["title"],
                details=data.get("details", ""),
                payload=data.get("payload"),
            )
            return jsonify(asdict(event)), 201

        except (ValueError, TypeError) as exc:
            return jsonify({"error": str(exc)}), 400
        except PermissionError:
            return jsonify({"error": "Owner access denied."}), 403


    @app.get("/api/owner/lifestyle/suggestions")
    @login_required
    def owner_lifestyle_suggestions():
        denied = require_owner_lifestyle_access()
        if denied:
            return denied
        try:
            from dataclasses import asdict
            suggestions = owner_lifestyle_service.list_pending_suggestions(
                g.principal, g.principal.business_id
            )
            return jsonify({"suggestions": [asdict(item) for item in suggestions]})
        except PermissionError:
            return jsonify({"error": "Owner access denied."}), 403

    @app.post("/api/owner/lifestyle/observations")
    @login_required
    def owner_lifestyle_observe():
        require_csrf(request)
        denied = require_owner_lifestyle_access()
        if denied:
            return denied
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"error": "Expected a JSON object."}), 400
        try:
            from dataclasses import asdict
            suggestion = owner_lifestyle_service.observe_routine(
                g.principal,
                g.principal.business_id,
                data.get("field_name"),
                data.get("proposed_value"),
            )
            return jsonify(asdict(suggestion)), 201
        except (ValueError, TypeError) as exc:
            return jsonify({"error": str(exc)}), 400
        except PermissionError:
            return jsonify({"error": "Owner access denied."}), 403

    @app.post("/api/owner/lifestyle/suggestions/<suggestion_id>/resolve")
    @login_required
    def owner_lifestyle_resolve(suggestion_id):
        require_csrf(request)
        denied = require_owner_lifestyle_access()
        if denied:
            return denied
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or type(data.get("accept")) is not bool:
            return jsonify({"error": "The accept field must be true or false."}), 400
        try:
            from dataclasses import asdict
            preferences = owner_lifestyle_service.resolve_suggestion(
                g.principal,
                g.principal.business_id,
                suggestion_id,
                data["accept"],
            )
            return jsonify(asdict(preferences))
        except LookupError:
            return jsonify({"error": "Suggestion not found."}), 404
        except (ValueError, TypeError) as exc:
            return jsonify({"error": str(exc)}), 400
        except PermissionError:
            return jsonify({"error": "Owner access denied."}), 403

    @app.post("/api/owner/subscriptions/<subscription_id>/cancel")
    @login_required
    def owner_cancel_subscription(subscription_id: str):
        require_csrf(request)

        if g.principal.role != UserRole.OWNER:
            return jsonify({"error": "Only the business owner may cancel a subscription."}), 403

        subscription = subscriptions.get_subscription(subscription_id)

        # Do not reveal whether another business owns this subscription.
        if (
            subscription is None
            or subscription["business_id"] != g.principal.business_id
        ):
            return jsonify({"error": "Subscription not found."}), 404

        data = request.get_json(silent=True)
        if not isinstance(data, dict) or type(data.get("at_period_end")) is not bool:
            return jsonify({
                "error": "Provide at_period_end as true or false."
            }), 400

        try:
            changed = subscriptions.cancel_subscription(
                subscription_id=subscription_id,
                cancelled_at=datetime.now(timezone.utc),
                at_period_end=data["at_period_end"],
            )
        except (ValueError, TypeError) as exc:
            return jsonify({"error": str(exc)}), 400

        return jsonify({
            "subscription_id": subscription_id,
            "cancellation_requested": True,
            "changed": changed,
            "at_period_end": data["at_period_end"],
            "provider_cancellation_performed": False,
            "business_access_changed": False,
        }), 200

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
        message = AssistantMessage(business.business_id, text)

        # The authenticated principal is the authoritative execution identity.
        # The AI provider never receives authority to construct this tenant.
        tenant = TenantContext(
            business_id=business.business_id,
            principal=g.principal,
        )

        history = web_conversations.load_history(
            user_id=g.principal.user_id,
            business_id=business.business_id,
        )

        try:
            result = builder(business).handle(
                message,
                tenant=tenant,
                conversation_history=history,
                channel="web",
            )
        except AIProviderError:
            return jsonify({
                "error": (
                    "The assistant is temporarily unavailable. "
                    "Please try again shortly."
                )
            }), 503

        if not isinstance(result, AssistantResponse):
            return jsonify({"error": "Assistant returned an invalid response."}), 500

        web_conversations.append_exchange(
            user_id=g.principal.user_id,
            business_id=business.business_id,
            user_content=text,
            assistant_content=result.message,
            created_at=datetime.now(timezone.utc),
        )

        response_data = {
            "assistant_name": result.assistant_name,
            "message": result.message,
            "should_speak": result.should_speak,
            "speech_available": False,
        }

        if result.should_speak:
            try:
                synthesizer = speech_synthesizer
                if synthesizer is None:
                    config = ElevenLabsConfig.from_environment()
                    synthesizer = ElevenLabsSpeechEngine(config)

                direction = result.speech_direction

                audio = synthesizer.synthesize(
                    SpeechRequest(
                        text=result.message,
                        voice=business.assistant_voice,
                        speed=1.0,
                        emotion=(
                            direction.emotion
                            if direction is not None
                            else "neutral"
                        ),
                        delivery=(
                            direction.delivery
                            if direction is not None
                            else "normal"
                        ),
                        pitch=(
                            direction.pitch
                            if direction is not None
                            else None
                        ),
                    )
                )

                if not isinstance(audio, bytes) or not audio:
                    raise RuntimeError("Speech provider returned invalid audio.")

                if len(audio) > 8 * 1024 * 1024:
                    raise RuntimeError("Speech response exceeded the web size limit.")

                response_data["speech_audio_base64"] = (
                    base64.b64encode(audio).decode("ascii")
                )
                response_data["speech_mime_type"] = "audio/mpeg"
                response_data["speech_available"] = True

            except Exception:
                # Text remains available even when speech synthesis fails.
                response_data["speech_error"] = (
                    "Voice playback is unavailable right now. "
                    "Your text response is ready."
                )

        return jsonify(response_data)

    return app


_forge_runner_lock = threading.Lock()
_forge_runner = None


def _ensure_process_forge_worker(
    capability_composition,
    processor: StructuredAssistantProcessor,
) -> None:
    """Start at most one production Forge worker in this process."""
    global _forge_runner

    enabled = os.getenv("AMINATION_FORGE_WORKER_ENABLED", "true")
    if enabled.strip().lower() not in {"1", "true", "yes", "on"}:
        return

    with _forge_runner_lock:
        if _forge_runner is not None and _forge_runner.is_running:
            return

        _forge_runner = capability_composition.start_brain_forge_worker(
            processor,
            worker_id=f"web-forge-{os.getpid()}",
            lease_seconds=300,
            poll_interval=1.0,
        )
        atexit.register(_forge_runner.stop)


def _production_runtime_builder(
    business: Business,
    *,
    database: SQLiteDatabase | None = None,
) -> OrchestratorLike:
    """Build the structured production assistant runtime for one business.

    This is the web composition root for E1.5e-3.

    The AI provider is limited to producing an untrusted AIResult.
    Capability authorization, confirmation, commercial access, tenant
    identity, safety enforcement, routing, and execution remain application
    owned.
    """
    if not isinstance(business, Business):
        raise TypeError("business must be a Business.")

    database = database or _production_database()

    try:
        config = GroqConfig.from_environment()
    except RuntimeError as exc:
        raise RuntimeError(
            "Cannot start assistant: Groq is not configured. "
            f"{exc}"
        ) from exc

    raw_provider = GroqHTTPProvider(config)
    structured_provider = ParsedRawAIProvider(raw_provider)

    capability_composition = build_production_capability_composition(
        database=database,
    )

    memory_context_builder = MemoryContextBuilder(
        capability_composition.memory_service,
    )

    processor = StructuredAssistantProcessor(
        ai_provider=structured_provider,
        memory_context_builder=memory_context_builder,
    )

    _ensure_process_forge_worker(
        capability_composition,
        processor,
    )

    confirmation_repository = SQLiteCapabilityConfirmationRepository(
        database,
    )
    confirmation_service = CapabilityConfirmationService(
        confirmation_repository,
    )

    commercial_access = BusinessAccessService(database)

    executor = capability_composition.executor_for_business(
        business.business_id,
    )

    return AssistantOrchestrator(
        business=business,
        processor=processor,
        executor=executor,
        capability_operation_policy=(
            capability_composition.operation_policy
        ),
        confirmation_service=confirmation_service,
        commercial_access=commercial_access,
    )


def _production_database() -> SQLiteDatabase:
    """Open the authoritative production application database."""
    database = SQLiteDatabase(
        os.getenv(
            "ASSISTANT_DB_PATH",
            "data/assistant.sqlite3",
        )
    )
    database.initialize()
    return database


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
