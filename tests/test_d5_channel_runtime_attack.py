from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.assistant.ai_capability_request import AICapabilityRequest
from app.assistant.ai_result import AIResult
from app.assistant.capability import Capability
from app.assistant.capability_confirmation_service import CapabilityConfirmationService
from app.assistant.capability_preparation import CapabilityExecutionPreparer
from app.assistant.execution import CapabilityExecutionRequest, CapabilityExecutionResult
from app.assistant.message import AssistantMessage
from app.assistant.orchestrator import AssistantOrchestrator
from app.assistant.structured_processor import StructuredAssistantProcessor
from app.commercial.access import BusinessAccessService
from app.commercial.state import BusinessCommercialState, CommercialStatus
from app.identity.models import AuthenticatedPrincipal, SessionScope, UserRole
from app.identity.tenant import TenantContext
from app.models.business import Business
from app.persistence.business_repository import SQLiteBusinessRepository
from app.persistence.capability_confirmation import SQLiteCapabilityConfirmationRepository
from app.persistence.capability_entitlement_repository import SQLiteCapabilityEntitlementRepository
from app.persistence.commercial_state_repository import SQLiteCommercialStateRepository
from app.persistence.database import SQLiteDatabase
from app.persistence.founder_repository import SQLiteFounderRepository
from app.persistence.platform_event_repository import SQLitePlatformEventRepository
from app.persistence.safety_repository import SQLiteSafetyRepository
from app.safety.models import SafetyControlScope, SafetyControlState
from app.safety.service import SafetyControlService
from app.trust.capability_executor import CapabilityExecutor
from app.trust.capability_operation_policy import CapabilityOperationPolicy


BUSINESS_ID = "business-d5-runtime"
USER_ID = "d5-runtime-user"
SESSION_ID = "d5-runtime-session"


class RecordingStructuredProcessor(StructuredAssistantProcessor):
    """Deterministic structured AI proposal layer."""

    def __init__(self, result: AIResult) -> None:
        self.result = result

    def process(
        self,
        message: AssistantMessage,
        automation_context=None,
        conversation_history=None,
    ) -> AIResult:
        assert message.business_id == BUSINESS_ID
        return self.result


def make_database(tmp_path: Path) -> SQLiteDatabase:
    database = SQLiteDatabase(tmp_path / "d5-channel-runtime.db")
    database.initialize()
    return database


def create_founder(database: SQLiteDatabase) -> None:
    with database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO users(user_id, display_name, email)
            VALUES (?, ?, ?)
            """,
            (
                "founder-d5-runtime",
                "D5 Runtime Founder",
                "founder-d5-runtime@example.test",
            ),
        )
        connection.execute(
            """
            INSERT INTO platform_founders(user_id, active)
            VALUES (?, ?)
            """,
            ("founder-d5-runtime", 1),
        )


def create_business(database: SQLiteDatabase) -> Business:
    business = Business(
        business_id=BUSINESS_ID,
        name="D5 Runtime Business",
        owner_name="Runtime Owner",
        assistant_name="Runtime Assistant",
        assistant_voice="female",
    )
    SQLiteBusinessRepository(database).save(business)

    SQLiteCommercialStateRepository(database).save(
        BusinessCommercialState(
            business_id=BUSINESS_ID,
            status=CommercialStatus.ACTIVE,
        )
    )

    SQLiteCapabilityEntitlementRepository(database).configure(
        BUSINESS_ID,
        frozenset({Capability.MEMORY}),
    )

    return business


def create_founder_principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id="founder-d5-runtime",
        business_id=None,
        role=None,
        session_id="founder-d5-runtime-session",
        scope=SessionScope.PLATFORM,
    )


def create_tenant() -> TenantContext:
    principal = AuthenticatedPrincipal(
        user_id=USER_ID,
        business_id=BUSINESS_ID,
        role=UserRole.OWNER,
        session_id=SESSION_ID,
    )
    return TenantContext(
        business_id=BUSINESS_ID,
        principal=principal,
    )


def make_message(business: Business) -> AssistantMessage:
    return AssistantMessage(
        business_id=business.business_id,
        content="Please remember the requested operation.",
    )


def make_save_request() -> AICapabilityRequest:
    return AICapabilityRequest(
        capability=Capability.MEMORY,
        operation="save",
        arguments={
            "memory_id": "d5-memory-001",
            "content": "D5 structured execution test memory.",
            "memory_type": "operational_fact",
            "importance": 5,
        },
        reason="Execute the requested structured memory operation.",
        reversible=True,
    )


def build_safety_service(database: SQLiteDatabase) -> SafetyControlService:
    from app.founder.authorization import FounderAuthorizationService

    return SafetyControlService(
        safety_repository=SQLiteSafetyRepository(database),
        founder_authorization=FounderAuthorizationService(
            SQLiteFounderRepository(database)
        ),
        platform_events=SQLitePlatformEventRepository(database),
    )


def build_orchestrator(
    database: SQLiteDatabase,
    business: Business,
    result: AIResult,
) -> AssistantOrchestrator:
    from app.assistant.capability_composition import (
        build_production_capability_composition,
    )

    composition = build_production_capability_composition(
        database=database,
    )

    confirmation_service = CapabilityConfirmationService(
        SQLiteCapabilityConfirmationRepository(database),
        clock=lambda: datetime(
            2026,
            9,
            20,
            15,
            30,
            tzinfo=timezone.utc,
        ),
    )

    commercial_access = BusinessAccessService(
        database,
        clock=lambda: datetime(
            2026,
            9,
            20,
            15,
            30,
            tzinfo=timezone.utc,
        ),
    )

    operation_policy = CapabilityOperationPolicy(
        confirmation_by_operation={
            Capability.MEMORY: {
                "save": False,
                "get": False,
                "list": False,
                "delete": True,
            }
        }
    )

    return AssistantOrchestrator(
        business=business,
        processor=RecordingStructuredProcessor(result),
        executor=composition.executor_for_business(BUSINESS_ID),
        capability_operation_policy=operation_policy,
        capability_preparer=CapabilityExecutionPreparer(),
        confirmation_service=confirmation_service,
        commercial_access=commercial_access,
    )


def make_direct_executor(database: SQLiteDatabase) -> CapabilityExecutor:
    from app.assistant.capability_composition import (
        build_production_capability_composition,
    )

    composition = build_production_capability_composition(
        database=database,
    )
    return composition.executor_for_business(BUSINESS_ID)


def halt_channel(
    service: SafetyControlService,
    principal: AuthenticatedPrincipal,
    channel: str,
):
    return service.halt(
        principal=principal,
        scope=SafetyControlScope.CHANNEL,
        target=channel,
        reason=f"D5 emergency halt for {channel}.",
    )


def recover_incident(
    service: SafetyControlService,
    principal: AuthenticatedPrincipal,
    incident_id: str,
) -> None:
    service.begin_investigation(principal, incident_id)
    service.resolve_incident(
        principal,
        incident_id,
        notes="Cause investigated and corrective action completed.",
    )
    service.verify_fix(
        principal,
        incident_id,
        notes="Corrective action verified by D5 runtime test.",
    )
    service.authorize_resume(principal, incident_id)


def execute_save_directly(
    database: SQLiteDatabase,
    *,
    channel: str,
    integration: str | None = None,
) -> CapabilityExecutionResult:
    request = CapabilityExecutionRequest(
        capability=Capability.MEMORY,
        operation="save",
        business_id=BUSINESS_ID,
        arguments=make_save_request().arguments,
        reason="D5 direct execution security test.",
        channel=channel,
        integration=integration,
    )

    return make_direct_executor(database).execute(
        request,
        tenant=create_tenant(),
    )


def test_web_channel_halt_blocks_real_orchestrator_execution(tmp_path):
    database = make_database(tmp_path)
    create_founder(database)
    business = create_business(database)

    safety_service = build_safety_service(database)
    halt_channel(safety_service, create_founder_principal(), "web")

    orchestrator = build_orchestrator(
        database,
        business,
        AIResult(capability_requests=(make_save_request(),)),
    )

    with pytest.raises(PermissionError):
        orchestrator.handle(
            make_message(business),
            tenant=create_tenant(),
            channel="web",
        )


def test_whatsapp_channel_halt_blocks_real_orchestrator_execution(tmp_path):
    database = make_database(tmp_path)
    create_founder(database)
    business = create_business(database)

    safety_service = build_safety_service(database)
    halt_channel(safety_service, create_founder_principal(), "whatsapp")

    orchestrator = build_orchestrator(
        database,
        business,
        AIResult(capability_requests=(make_save_request(),)),
    )

    with pytest.raises(PermissionError):
        orchestrator.handle(
            make_message(business),
            tenant=create_tenant(),
            channel="whatsapp",
        )


def test_web_halt_does_not_block_whatsapp_runtime_execution(tmp_path):
    database = make_database(tmp_path)
    create_founder(database)
    business = create_business(database)

    safety_service = build_safety_service(database)
    halt_channel(safety_service, create_founder_principal(), "web")

    orchestrator = build_orchestrator(
        database,
        business,
        AIResult(capability_requests=(make_save_request(),)),
    )

    response = orchestrator.handle(
        make_message(business),
        tenant=create_tenant(),
        channel="whatsapp",
    )

    assert response.business_id == BUSINESS_ID
    assert response.message is not None


def test_full_channel_recovery_restores_real_runtime_execution(tmp_path):
    database = make_database(tmp_path)
    create_founder(database)
    business = create_business(database)

    founder = create_founder_principal()
    safety_service = build_safety_service(database)
    control = halt_channel(safety_service, founder, "web")

    orchestrator = build_orchestrator(
        database,
        business,
        AIResult(capability_requests=(make_save_request(),)),
    )

    with pytest.raises(PermissionError):
        orchestrator.handle(
            make_message(business),
            tenant=create_tenant(),
            channel="web",
        )

    recover_incident(
        safety_service,
        founder,
        control.incident_id,
    )
    safety_service.resume_control(
        founder,
        control.control_id,
    )

    response = orchestrator.handle(
        make_message(business),
        tenant=create_tenant(),
        channel="web",
    )

    assert response.business_id == BUSINESS_ID
    assert response.message is not None


def test_channel_halt_survives_fresh_runtime_construction(tmp_path):
    database = make_database(tmp_path)
    create_founder(database)
    business = create_business(database)

    founder = create_founder_principal()
    safety_service = build_safety_service(database)
    halt_channel(safety_service, founder, "whatsapp")

    first = build_orchestrator(
        database,
        business,
        AIResult(capability_requests=(make_save_request(),)),
    )

    with pytest.raises(PermissionError):
        first.handle(
            make_message(business),
            tenant=create_tenant(),
            channel="whatsapp",
        )

    second = build_orchestrator(
        SQLiteDatabase(database.path),
        business,
        AIResult(capability_requests=(make_save_request(),)),
    )

    with pytest.raises(PermissionError):
        second.handle(
            make_message(business),
            tenant=create_tenant(),
            channel="whatsapp",
        )


def test_direct_executor_cannot_bypass_halted_channel(tmp_path):
    database = make_database(tmp_path)
    create_founder(database)
    create_business(database)

    safety_service = build_safety_service(database)
    halt_channel(safety_service, create_founder_principal(), "web")

    with pytest.raises(PermissionError):
        execute_save_directly(
            database,
            channel="web",
        )


def test_direct_executor_cannot_bypass_halted_business(tmp_path):
    database = make_database(tmp_path)
    create_founder(database)
    create_business(database)

    founder = create_founder_principal()
    safety_service = build_safety_service(database)

    control = safety_service.halt(
        founder,
        scope=SafetyControlScope.BUSINESS,
        target=BUSINESS_ID,
        reason="D5 direct-executor attack test.",
    )

    with pytest.raises(PermissionError):
        execute_save_directly(
            database,
            channel="whatsapp",
        )

    assert control.state is SafetyControlState.HALTED


def test_ai_cannot_disable_safety_by_controlling_execution_fields(tmp_path):
    database = make_database(tmp_path)
    create_founder(database)
    create_business(database)

    request = make_save_request()

    assert not hasattr(request, "channel")
    assert not hasattr(request, "integration")
    assert not hasattr(request, "business_id")

    with pytest.raises(AttributeError):
        request.channel = "web"


def test_ai_generated_capability_cannot_execute_when_capability_is_halted(tmp_path):
    database = make_database(tmp_path)
    create_founder(database)
    business = create_business(database)

    safety_service = build_safety_service(database)
    safety_service.halt(
        create_founder_principal(),
        scope=SafetyControlScope.CAPABILITY,
        target=Capability.MEMORY.value,
        reason="D5 AI capability-manipulation attack test.",
    )

    orchestrator = build_orchestrator(
        database,
        business,
        AIResult(capability_requests=(make_save_request(),)),
    )

    with pytest.raises(PermissionError):
        orchestrator.handle(
            make_message(business),
            tenant=create_tenant(),
            channel="web",
        )


def test_ai_generated_capability_cannot_execute_when_integration_is_halted(
    tmp_path,
):
    database = make_database(tmp_path)
    create_founder(database)
    create_business(database)

    safety_service = build_safety_service(database)
    safety_service.halt(
        create_founder_principal(),
        scope=SafetyControlScope.INTEGRATION,
        target="calendar",
        reason="D5 AI integration-manipulation attack test.",
    )

    with pytest.raises(PermissionError):
        execute_save_directly(
            database,
            channel="web",
            integration="calendar",
        )
