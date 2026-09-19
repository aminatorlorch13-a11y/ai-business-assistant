from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from app.ai.context import AIContext
from app.ai.provider import AIProvider
from app.assistant.action import AssistantAction
from app.assistant.action_executor import ActionExecutor
from app.assistant.intent import AssistantIntent
from app.assistant.interpretation import AIInterpretation
from app.assistant.interpretation_validator import AIInterpretationValidator
from app.assistant.message import AssistantMessage
from app.assistant.orchestrator import AssistantOrchestrator
from app.assistant.processor import AssistantProcessor
from app.identity.models import AuthenticatedPrincipal, SessionScope, UserRole
from app.memory.context import MemoryContext
from app.memory.context import MemoryContextBuilder
from app.persistence.business_repository import SQLiteBusinessRepository
from app.persistence.database import SQLiteDatabase
from app.persistence.founder_repository import SQLiteFounderRepository
from app.persistence.platform_event_repository import SQLitePlatformEventRepository
from app.persistence.safety_repository import SQLiteSafetyRepository
from app.models.business import Business
from app.safety.enforcement import SafetyEnforcement
from app.safety.models import SafetyControlScope, SafetyControlState
from app.safety.service import SafetyControlService
from app.services.business_operation import BusinessOperation
from app.trust.action_policy import ActionPolicy
from app.web.access import BusinessAccessService
from app.identity.tenant import TenantContext


class RecordingAIProvider(AIProvider):
    """
    Deterministic AI provider.

    The AI always returns a valid business action. The test therefore proves
    that emergency safety enforcement, rather than AI cooperation, is what
    prevents execution.
    """

    def interpret(
        self,
        message: AssistantMessage,
        context: AIContext,
    ) -> AIInterpretation:
        assert context.memory_context.business_id == message.business_id

        intent = AssistantIntent(
            business_id=message.business_id,
            intent_type="business_task",
            instruction="Create the requested business operation.",
        )

        action = AssistantAction(
            business_id=message.business_id,
            action_type="create",
            target="appointment",
            instruction="Perform the requested operation.",
        )

        return AIInterpretation(
            intent=intent,
            action=action,
        )


class RecordingOperation(BusinessOperation):
    def __init__(self) -> None:
        self.calls: list[str] = []

    def execute(
        self,
        action: AssistantAction,
        tenant: TenantContext | None = None,
    ) -> str:
        self.calls.append(action.action_type)
        return "operation executed"


def make_database(tmp_path) -> SQLiteDatabase:
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
        business_id="business-d5-runtime",
        name="D5 Runtime Business",
        owner_name="Runtime Owner",
        assistant_name="Runtime Assistant",
        assistant_voice="female",
    )

    SQLiteBusinessRepository(database).save(business)

    return business


def create_founder_principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id="founder-d5-runtime",
        business_id=None,
        role=None,
        session_id="founder-d5-runtime-session",
        scope=SessionScope.PLATFORM,
    )


def build_runtime(
    database: SQLiteDatabase,
    business: Business,
    operation: RecordingOperation,
) -> AssistantOrchestrator:
    memory_context_builder = Mock(spec=MemoryContextBuilder)
    memory_context_builder.build.return_value = MemoryContext(
        business_id=business.business_id,
        memories=(),
    )

    processor = AssistantProcessor(
        ai_provider=RecordingAIProvider(),
        validator=AIInterpretationValidator(),
        memory_context_builder=memory_context_builder,
    )

    safety_repository = SQLiteSafetyRepository(database)
    safety_enforcement = SafetyEnforcement(safety_repository)

    executor = ActionExecutor(
        policy=ActionPolicy(allow_create=True),
        operation=operation,
        safety_enforcement=safety_enforcement,
    )

    return AssistantOrchestrator(
        business=business,
        processor=processor,
        executor=executor,
    )


def build_safety_service(
    database: SQLiteDatabase,
) -> SafetyControlService:
    safety_repository = SQLiteSafetyRepository(database)
    founder_repository = SQLiteFounderRepository(database)
    platform_events = SQLitePlatformEventRepository(database)

    return SafetyControlService(
        safety_repository=safety_repository,
        founder_authorization=__import__(
            "app.founder.authorization",
            fromlist=["FounderAuthorizationService"],
        ).FounderAuthorizationService(founder_repository),
        platform_events=platform_events,
    )


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


def make_message(business: Business) -> AssistantMessage:
    return AssistantMessage(
        business_id=business.business_id,
        content="Please create the requested operation.",
    )


def test_web_channel_halt_blocks_real_orchestrator_execution(tmp_path):
    database = make_database(tmp_path)
    create_founder(database)
    business = create_business(database)

    founder = create_founder_principal()
    safety_service = build_safety_service(database)

    halt_channel(safety_service, founder, "web")

    operation = RecordingOperation()
    orchestrator = build_runtime(database, business, operation)

    with pytest.raises(PermissionError):
        orchestrator.handle(
            make_message(business),
            confirmed=True,
            channel="web",
        )

    assert operation.calls == []


def test_whatsapp_channel_halt_blocks_real_orchestrator_execution(tmp_path):
    database = make_database(tmp_path)
    create_founder(database)
    business = create_business(database)

    founder = create_founder_principal()
    safety_service = build_safety_service(database)

    halt_channel(safety_service, founder, "whatsapp")

    operation = RecordingOperation()
    orchestrator = build_runtime(database, business, operation)

    with pytest.raises(PermissionError):
        orchestrator.handle(
            make_message(business),
            confirmed=True,
            channel="whatsapp",
        )

    assert operation.calls == []


def test_web_halt_does_not_block_whatsapp_runtime_execution(tmp_path):
    database = make_database(tmp_path)
    create_founder(database)
    business = create_business(database)

    founder = create_founder_principal()
    safety_service = build_safety_service(database)

    halt_channel(safety_service, founder, "web")

    operation = RecordingOperation()
    orchestrator = build_runtime(database, business, operation)

    response = orchestrator.handle(
        make_message(business),
        confirmed=True,
        channel="whatsapp",
    )

    assert response.business_id == business.business_id
    assert response.message == "operation executed"
    assert operation.calls == ["create"]


def test_full_channel_recovery_restores_real_runtime_execution(tmp_path):
    database = make_database(tmp_path)
    create_founder(database)
    business = create_business(database)

    founder = create_founder_principal()
    safety_service = build_safety_service(database)

    control = halt_channel(safety_service, founder, "web")

    operation = RecordingOperation()
    orchestrator = build_runtime(database, business, operation)

    with pytest.raises(PermissionError):
        orchestrator.handle(
            make_message(business),
            confirmed=True,
            channel="web",
        )

    assert operation.calls == []

    recover_incident(
        safety_service,
        founder,
        control.incident_id,
    )

    safety_service.resume_control(founder, control.control_id)

    response = orchestrator.handle(
        make_message(business),
        confirmed=True,
        channel="web",
    )

    assert response.business_id == business.business_id
    assert response.message == "operation executed"
    assert operation.calls == ["create"]


def test_channel_halt_survives_fresh_runtime_construction(tmp_path):
    database = make_database(tmp_path)
    create_founder(database)
    business = create_business(database)

    founder = create_founder_principal()
    safety_service = build_safety_service(database)

    halt_channel(safety_service, founder, "whatsapp")

    first_operation = RecordingOperation()
    first_orchestrator = build_runtime(
        database,
        business,
        first_operation,
    )

    with pytest.raises(PermissionError):
        first_orchestrator.handle(
            make_message(business),
            confirmed=True,
            channel="whatsapp",
        )

    assert first_operation.calls == []

    # Construct a completely fresh runtime against the same database.
    second_operation = RecordingOperation()
    second_orchestrator = build_runtime(
        SQLiteDatabase(database.path),
        business,
        second_operation,
    )

    with pytest.raises(PermissionError):
        second_orchestrator.handle(
            make_message(business),
            confirmed=True,
            channel="whatsapp",
        )

    assert second_operation.calls == []


def test_direct_executor_cannot_bypass_halted_channel(tmp_path):
    """Calling ActionExecutor directly must still enforce the safety gate."""
    database = make_database(tmp_path)
    create_founder(database)
    business = create_business(database)

    founder = create_founder_principal()
    safety_service = build_safety_service(database)
    halt_channel(safety_service, founder, "web")

    operation = RecordingOperation()
    orchestrator = build_runtime(database, business, operation)

    executor = orchestrator._executor

    action = AssistantAction(
        business_id=business.business_id,
        action_type="create",
        target="appointment",
        instruction="Create the requested appointment.",
        reversible=False,
    )

    with pytest.raises(PermissionError):
        executor.execute(
            action,
            confirmed=True,
            tenant=None,
            channel="web",
        )

    assert operation.calls == []


def test_direct_executor_cannot_bypass_halted_business(tmp_path):
    """The business kill-switch must remain effective below the orchestrator."""
    database = make_database(tmp_path)
    create_founder(database)
    business = create_business(database)

    founder = create_founder_principal()
    safety_service = build_safety_service(database)

    control = safety_service.halt(
        founder,
        scope=SafetyControlScope.BUSINESS,
        target=business.business_id,
        reason="D5 direct-executor attack test.",
    )

    operation = RecordingOperation()
    orchestrator = build_runtime(database, business, operation)

    action = AssistantAction(
        business_id=business.business_id,
        action_type="create",
        target="appointment",
        instruction="Create the requested appointment.",
        reversible=False,
    )

    with pytest.raises(PermissionError):
        orchestrator._executor.execute(
            action,
            confirmed=True,
            tenant=None,
            channel="whatsapp",
        )

    assert control.state is SafetyControlState.HALTED
    assert operation.calls == []


def test_ai_cannot_disable_safety_by_controlling_action_fields(tmp_path):
    """
    AI-generated AssistantAction contains business/action data only.
    Channel safety remains an execution-context decision outside the AI.
    """
    database = make_database(tmp_path)
    create_founder(database)
    business = create_business(database)

    operation = RecordingOperation()
    orchestrator = build_runtime(database, business, operation)

    action = AssistantAction(
        business_id=business.business_id,
        action_type="create",
        target="appointment",
        instruction="Create the requested appointment.",
        reversible=False,
    )

    assert not hasattr(action, "channel")
    assert not hasattr(action, "integration")

    with pytest.raises(AttributeError):
        action.channel = "web"


def test_ai_generated_action_cannot_execute_when_capability_is_halted(tmp_path):
    """
    A valid AI-generated action must still be blocked when its capability
    has been emergency-disabled.
    """
    database = make_database(tmp_path)
    create_founder(database)
    business = create_business(database)

    founder = create_founder_principal()
    safety_service = build_safety_service(database)

    safety_service.halt(
        founder,
        scope=SafetyControlScope.CAPABILITY,
        target="create",
        reason="D5 AI capability-manipulation attack test.",
    )

    operation = RecordingOperation()
    orchestrator = build_runtime(database, business, operation)

    with pytest.raises(PermissionError):
        orchestrator.handle(
            make_message(business),
            confirmed=True,
            channel="web",
        )

    assert operation.calls == []


def test_ai_generated_action_cannot_execute_when_integration_is_halted(tmp_path):
    """
    Integration safety is enforced by the execution boundary rather than
    by the AI interpretation.
    """
    database = make_database(tmp_path)
    create_founder(database)
    business = create_business(database)

    founder = create_founder_principal()
    safety_service = build_safety_service(database)

    safety_service.halt(
        founder,
        scope=SafetyControlScope.INTEGRATION,
        target="calendar",
        reason="D5 AI integration-manipulation attack test.",
    )

    operation = RecordingOperation()
    orchestrator = build_runtime(database, business, operation)

    action = AssistantAction(
        business_id=business.business_id,
        action_type="create",
        target="appointment",
        instruction="Create the requested appointment.",
        reversible=False,
    )

    with pytest.raises(PermissionError):
        orchestrator._executor.execute(
            action,
            confirmed=True,
            tenant=None,
            channel="web",
            integration="calendar",
        )

    assert operation.calls == []
