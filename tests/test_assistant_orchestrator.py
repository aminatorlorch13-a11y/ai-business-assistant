import pytest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock


from app.assistant.ai_capability_request import AICapabilityRequest
from app.assistant.ai_result import AIResult
from app.assistant.capability import Capability
from app.assistant.capability_confirmation_service import (
    CapabilityConfirmationService,
)
from app.assistant.capability_preparation import CapabilityExecutionPreparer
from app.assistant.execution import (
    CapabilityExecutionRequest,
    CapabilityExecutionResult,
)
from app.assistant.message import AssistantMessage
from app.assistant.orchestrator import AssistantOrchestrator
from app.assistant.structured_processor import StructuredAssistantProcessor
from app.commercial.access import BusinessAccessService
from app.commercial.state import BusinessCommercialState, CommercialStatus
from app.persistence.commercial_state_repository import SQLiteCommercialStateRepository
from app.identity.models import AuthenticatedPrincipal, UserRole
from app.identity.tenant import TenantContext
from app.models.business import Business
from app.persistence.capability_confirmation import (
    SQLiteCapabilityConfirmationRepository,
)
from app.persistence.database import SQLiteDatabase
from app.trust.capability_executor import CapabilityExecutor
from app.trust.capability_operation_policy import CapabilityOperationPolicy




BUSINESS_ID = "business-001"


def make_business() -> Business:
    return Business(
        business_id=BUSINESS_ID,
        name="Business One",
        owner_name="Owner One",
        assistant_name="Business Assistant",
        assistant_voice="female",
    )


def make_tenant(business_id: str = BUSINESS_ID) -> TenantContext:
    principal = AuthenticatedPrincipal(
        user_id="user-001",
        business_id=business_id,
        role=UserRole.OWNER,
        session_id="session-001",
    )
    return TenantContext(
        business_id=business_id,
        principal=principal,
    )


def make_save_request() -> AICapabilityRequest:
    return AICapabilityRequest(
        capability=Capability.MEMORY,
        operation="save",
        arguments={
            "memory_id": "memory-001",
            "content": "Customer prefers email.",
            "memory_type": "customer_preference",
            "importance": 5,
        },
        reason="Remember customer's preference.",
        reversible=True,
    )


def make_structured_stack(tmp_path: Path):
    processor = Mock(spec=StructuredAssistantProcessor)
    executor = Mock(spec=CapabilityExecutor)

    database = SQLiteDatabase(tmp_path / "orchestrator.sqlite3")
    database.initialize()

    with database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO businesses(
                business_id,
                name,
                owner_name,
                assistant_name,
                assistant_voice
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                BUSINESS_ID,
                "Business One",
                "Owner One",
                "Business Assistant",
                "female",
            ),
        )
        connection.execute(
            """
            INSERT INTO users(
                user_id,
                display_name,
                email
            )
            VALUES (?, ?, ?)
            """,
            (
                "user-001",
                "Owner One",
                "owner@example.com",
            ),
        )

    SQLiteCommercialStateRepository(database).save(
        BusinessCommercialState(
            BUSINESS_ID,
            CommercialStatus.ACTIVE,
        )
    )

    confirmation_repository = SQLiteCapabilityConfirmationRepository(
        database
    )
    confirmation_service = CapabilityConfirmationService(
        confirmation_repository,
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

    # The production signup path normally provisions these records.
    # Tests create them explicitly so the security boundary is real.
    with database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO business_capability_entitlements(
                business_id,
                configured_at
            )
            VALUES (?, ?)
            """,
            (
                BUSINESS_ID,
                "2026-09-20T15:30:00+00:00",
            ),
        )
        connection.execute(
            """
            INSERT INTO business_capability_grants(
                business_id,
                capability
            )
            VALUES (?, ?)
            """,
            (
                BUSINESS_ID,
                "memory",
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

    return (
        processor,
        executor,
        operation_policy,
        confirmation_service,
        commercial_access,
        database,
    )



def make_orchestrator(
    processor,
    executor,
    policy,
    confirmation_service,
    commercial_access,
):
    return AssistantOrchestrator(
        business=make_business(),
        processor=processor,
        executor=executor,
        capability_operation_policy=policy,
        confirmation_service=confirmation_service,
        commercial_access=commercial_access,
    )


def test_orchestrator_executes_interpreted_action(tmp_path):
    processor, executor, policy, confirmation_service, commercial_access, _database = (
        make_structured_stack(tmp_path)
    )

    processor.process.return_value = AIResult(
        capability_requests=(make_save_request(),)
    )
    executor.execute.return_value = CapabilityExecutionResult(
        success=True,
        capability=Capability.MEMORY,
        operation="save",
        business_id=BUSINESS_ID,
        data="Memory saved.",
    )

    orchestrator = make_orchestrator(
        processor,
        executor,
        policy,
        confirmation_service,
        commercial_access,
    )

    message = AssistantMessage(
        business_id=BUSINESS_ID,
        content="Please remember that the customer prefers email.",
    )

    result = orchestrator.handle(
        message,
        tenant=make_tenant(),
    )

    assert result.message == "Memory saved."
    processor.process.assert_called_once()
    executor.execute.assert_called_once()

    request = executor.execute.call_args.args[0]
    assert isinstance(request, CapabilityExecutionRequest)
    assert request.capability is Capability.MEMORY
    assert request.operation == "save"
    assert request.business_id == BUSINESS_ID


def test_orchestrator_rejects_interpretation_for_another_business(tmp_path):
    processor, executor, policy, confirmation_service, commercial_access, _database = (
        make_structured_stack(tmp_path)
    )

    orchestrator = make_orchestrator(
        processor,
        executor,
        policy,
        confirmation_service,
        commercial_access,
    )

    with pytest.raises(
        ValueError,
        match="Execution tenant does not belong to this message business",
    ):
        orchestrator.handle(
            AssistantMessage(
                business_id=BUSINESS_ID,
                content="Please remember this.",
            ),
            tenant=make_tenant("business-999"),
        )

    processor.process.assert_not_called()
    executor.execute.assert_not_called()


def test_orchestrator_does_not_return_success_when_execution_fails(tmp_path):
    processor, executor, policy, confirmation_service, commercial_access, _database = (
        make_structured_stack(tmp_path)
    )

    processor.process.return_value = AIResult(
        capability_requests=(make_save_request(),)
    )
    executor.execute.return_value = CapabilityExecutionResult(
        success=False,
        capability=Capability.MEMORY,
        operation="save",
        business_id=BUSINESS_ID,
        error="Memory persistence failed.",
    )

    orchestrator = make_orchestrator(
        processor,
        executor,
        policy,
        confirmation_service,
        commercial_access,
    )

    result = orchestrator.handle(
        AssistantMessage(
            business_id=BUSINESS_ID,
            content="Please remember this.",
        ),
        tenant=make_tenant(),
    )

    assert result.message == "Memory persistence failed."
    assert "successfully" not in result.message.lower()
    executor.execute.assert_called_once()


def test_orchestrator_forwards_authenticated_tenant_to_executor(tmp_path):
    processor, executor, policy, confirmation_service, commercial_access, _database = (
        make_structured_stack(tmp_path)
    )

    processor.process.return_value = AIResult(
        capability_requests=(make_save_request(),)
    )
    executor.execute.return_value = CapabilityExecutionResult(
        success=True,
        capability=Capability.MEMORY,
        operation="save",
        business_id=BUSINESS_ID,
        data="Memory saved.",
    )

    orchestrator = make_orchestrator(
        processor,
        executor,
        policy,
        confirmation_service,
        commercial_access,
    )

    tenant = make_tenant()

    orchestrator.handle(
        AssistantMessage(
            business_id=BUSINESS_ID,
            content="Please remember this.",
        ),
        tenant=tenant,
    )

    executor.execute.assert_called_once()
    assert executor.execute.call_args.kwargs["tenant"] is tenant


def test_orchestrator_rejects_wrong_execution_tenant_before_processing(tmp_path):
    processor, executor, policy, confirmation_service, commercial_access, _database = (
        make_structured_stack(tmp_path)
    )

    orchestrator = make_orchestrator(
        processor,
        executor,
        policy,
        confirmation_service,
        commercial_access,
    )

    with pytest.raises(
        ValueError,
        match="Execution tenant does not belong to this message business",
    ):
        orchestrator.handle(
            AssistantMessage(
                business_id=BUSINESS_ID,
                content="Please remember this.",
            ),
            tenant=make_tenant("business-999"),
        )

    processor.process.assert_not_called()
    executor.execute.assert_not_called()


def test_orchestrator_rejects_invalid_tenant_before_processing(tmp_path):
    processor, executor, policy, confirmation_service, commercial_access, _database = (
        make_structured_stack(tmp_path)
    )

    orchestrator = make_orchestrator(
        processor,
        executor,
        policy,
        confirmation_service,
        commercial_access,
    )

    with pytest.raises(
        TypeError,
        match="tenant must be a TenantContext or None",
    ):
        orchestrator.handle(
            AssistantMessage(
                business_id=BUSINESS_ID,
                content="Please remember this.",
            ),
            tenant=object(),
        )

    processor.process.assert_not_called()
    executor.execute.assert_not_called()


def test_orchestrator_preserves_existing_web_execution_without_tenant(tmp_path):
    processor, executor, policy, confirmation_service, commercial_access, _database = (
        make_structured_stack(tmp_path)
    )

    processor.process.return_value = AIResult(
        capability_requests=(make_save_request(),)
    )
    executor.execute.return_value = CapabilityExecutionResult(
        success=True,
        capability=Capability.MEMORY,
        operation="save",
        business_id=BUSINESS_ID,
        data="Memory saved.",
    )

    orchestrator = make_orchestrator(
        processor,
        executor,
        policy,
        confirmation_service,
        commercial_access,
    )

    with pytest.raises(
        PermissionError,
        match="Authenticated tenant context is required for capability execution",
    ):
        orchestrator.handle(
            AssistantMessage(
                business_id=BUSINESS_ID,
                content="Please remember this.",
            ),
            channel="web",
        )

    processor.process.assert_called_once()
    executor.execute.assert_not_called()
