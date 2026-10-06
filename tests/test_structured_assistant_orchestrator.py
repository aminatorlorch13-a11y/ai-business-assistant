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


def make_tenant(
    business_id: str = BUSINESS_ID,
) -> TenantContext:
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


def make_delete_request(
    *,
    reversible: bool = True,
) -> AICapabilityRequest:
    return AICapabilityRequest(
        capability=Capability.MEMORY,
        operation="delete",
        arguments={"memory_id": "memory-001"},
        reason="Remove the requested memory.",
        reversible=reversible,
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
        reason="Remember the customer's preference.",
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
    operation_policy,
    confirmation_service,
    commercial_access,
) -> AssistantOrchestrator:
    return AssistantOrchestrator(
        business=make_business(),
        processor=processor,
        executor=executor,
        capability_operation_policy=operation_policy,
        capability_preparer=CapabilityExecutionPreparer(),
        confirmation_service=confirmation_service,
        commercial_access=commercial_access,
    )


def test_response_only_ai_result_does_not_execute(tmp_path):
    processor, executor, policy, confirmation_service, commercial_access, _ = make_structured_stack(tmp_path)

    processor.process.return_value = AIResult(
        response="I can help with that."
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
            content="Hello.",
        )
    )

    assert result.message == "I can help with that."
    executor.execute.assert_not_called()


def test_unconfirmed_delete_requires_confirmation_and_does_not_execute(tmp_path):
    processor, executor, policy, confirmation_service, commercial_access, _ = make_structured_stack(tmp_path)

    processor.process.return_value = AIResult(
        capability_requests=(make_delete_request(),)
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
            content="Delete that memory.",
        ),
        tenant=make_tenant(),
    )

    assert "Confirmation required" in result.message
    assert executor.execute.call_count == 0


def test_ai_reversible_flag_cannot_remove_confirmation_requirement(tmp_path):
    processor, executor, policy, confirmation_service, commercial_access, _ = make_structured_stack(tmp_path)

    processor.process.return_value = AIResult(
        capability_requests=(
            make_delete_request(reversible=True),
        )
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
            content="Delete that memory.",
        ),
        tenant=make_tenant(),
    )

    assert "Confirmation required" in result.message
    executor.execute.assert_not_called()


def test_confirmation_executes_exact_pending_request_without_reprocessing_ai(tmp_path):
    processor, executor, policy, confirmation_service, commercial_access, _ = make_structured_stack(tmp_path)

    processor.process.return_value = AIResult(
        capability_requests=(make_delete_request(),)
    )

    executor.execute.return_value = CapabilityExecutionResult(
        success=True,
        capability=Capability.MEMORY,
        operation="delete",
        business_id=BUSINESS_ID,
        data=True,
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
        content="Delete that memory.",
    )
    tenant = make_tenant()

    first = orchestrator.handle(
        message,
        tenant=tenant,
        channel="web",
        integration="internal",
    )

    assert "Confirmation required" in first.message
    assert "Confirmation ID:" in first.message
    processor.process.assert_called_once()

    confirmation_id = first.message.split("Confirmation ID: ", 1)[1]

    second = orchestrator.handle(
        message,
        tenant=tenant,
        confirmation_id=confirmation_id,
        channel="web",
        integration="internal",
    )

    assert second.message == "True"
    processor.process.assert_called_once()
    executor.execute.assert_called_once()

    executed_request = executor.execute.call_args.args[0]

    assert isinstance(
        executed_request,
        CapabilityExecutionRequest,
    )
    assert executed_request.capability is Capability.MEMORY
    assert executed_request.operation == "delete"
    assert executed_request.business_id == BUSINESS_ID
    assert executed_request.arguments == {
        "memory_id": "memory-001",
    }


def test_confirmation_without_id_is_rejected(tmp_path):
    processor, executor, policy, confirmation_service, commercial_access, _ = make_structured_stack(tmp_path)

    orchestrator = make_orchestrator(
        processor,
        executor,
        policy,
        confirmation_service,
        commercial_access,
    )

    with pytest.raises(
        ValueError,
        match="confirmation_id",
    ):
        orchestrator.handle(
            AssistantMessage(
                business_id=BUSINESS_ID,
                content="Yes.",
            ),
            confirmed=True,
            tenant=make_tenant(),
        )

    processor.process.assert_not_called()
    executor.execute.assert_not_called()


def test_capability_execution_requires_authenticated_tenant(tmp_path):
    processor, executor, policy, confirmation_service, commercial_access, _ = make_structured_stack(tmp_path)

    processor.process.return_value = AIResult(
        capability_requests=(make_save_request(),)
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
        match="Authenticated tenant context is required",
    ):
        orchestrator.handle(
            AssistantMessage(
                business_id=BUSINESS_ID,
                content="Remember this.",
            )
        )

    executor.execute.assert_not_called()


def test_cross_business_tenant_is_rejected_before_processing(tmp_path):
    processor, executor, policy, confirmation_service, commercial_access, _ = make_structured_stack(tmp_path)

    orchestrator = make_orchestrator(
        processor,
        executor,
        policy,
        confirmation_service,
        commercial_access,
    )

    with pytest.raises(
        ValueError,
        match="Execution tenant does not belong",
    ):
        orchestrator.handle(
            AssistantMessage(
                business_id=BUSINESS_ID,
                content="Remember this.",
            ),
            tenant=make_tenant("business-999"),
        )

    processor.process.assert_not_called()
    executor.execute.assert_not_called()


def test_successful_non_confirmed_capability_executes_through_executor(tmp_path):
    processor, executor, policy, confirmation_service, commercial_access, _ = make_structured_stack(tmp_path)

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

    result = orchestrator.handle(
        AssistantMessage(
            business_id=BUSINESS_ID,
            content="Remember that the customer prefers email.",
        ),
        tenant=make_tenant(),
    )

    assert result.message == "Memory saved."
    executor.execute.assert_called_once()

    executed_request = executor.execute.call_args.args[0]

    assert executed_request.capability is Capability.MEMORY
    assert executed_request.operation == "save"
    assert executed_request.business_id == BUSINESS_ID


def test_confirmation_survives_new_orchestrator_instance(tmp_path):
    processor, executor, policy, confirmation_service, commercial_access, database = make_structured_stack(tmp_path)

    processor.process.return_value = AIResult(
        capability_requests=(make_delete_request(),)
    )
    executor.execute.return_value = CapabilityExecutionResult(
        success=True,
        capability=Capability.MEMORY,
        operation="delete",
        business_id=BUSINESS_ID,
        data=True,
    )

    first_orchestrator = make_orchestrator(
        processor,
        executor,
        policy,
        confirmation_service,
        commercial_access,
    )
    tenant = make_tenant()
    message = AssistantMessage(
        business_id=BUSINESS_ID,
        content="Delete that memory.",
    )

    first = first_orchestrator.handle(
        message,
        tenant=tenant,
        channel="web",
        integration="internal",
    )

    confirmation_id = first.message.split("Confirmation ID: ", 1)[1]

    new_confirmation_service = CapabilityConfirmationService(
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

    second_orchestrator = make_orchestrator(
        processor,
        executor,
        policy,
        new_confirmation_service,
        commercial_access,
    )

    result = second_orchestrator.handle(
        message,
        tenant=tenant,
        confirmation_id=confirmation_id,
        channel="web",
        integration="internal",
    )

    assert result.message == "True"
    processor.process.assert_called_once()
    executor.execute.assert_called_once()


def test_confirmation_wrong_channel_cannot_execute(tmp_path):
    processor, executor, policy, confirmation_service, commercial_access, _ = make_structured_stack(tmp_path)

    processor.process.return_value = AIResult(
        capability_requests=(make_delete_request(),)
    )

    orchestrator = make_orchestrator(
        processor,
        executor,
        policy,
        confirmation_service,
        commercial_access,
    )

    tenant = make_tenant()
    first = orchestrator.handle(
        AssistantMessage(BUSINESS_ID, "Delete it."),
        tenant=tenant,
        channel="web",
        integration="internal",
    )

    confirmation_id = first.message.split("Confirmation ID: ", 1)[1]

    with pytest.raises(PermissionError, match="confirmation"):
        orchestrator.handle(
            AssistantMessage(BUSINESS_ID, "Yes."),
            tenant=tenant,
            confirmation_id=confirmation_id,
            channel="whatsapp",
            integration="internal",
        )

    executor.execute.assert_not_called()
