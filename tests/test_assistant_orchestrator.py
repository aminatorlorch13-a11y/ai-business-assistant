import pytest
from unittest.mock import Mock

from app.assistant.action import AssistantAction
from app.assistant.interpretation import AIInterpretation
from app.assistant.intent import AssistantIntent
from app.assistant.message import AssistantMessage
from app.assistant.orchestrator import AssistantOrchestrator
from app.assistant.response import AssistantResponse
from app.models.business import Business


def make_business() -> Business:
    return Business(
        business_id="business-001",
        name="Business One",
        owner_name="Owner One",
        assistant_name="Business Assistant",
        assistant_voice="female",
    )


def make_interpretation() -> AIInterpretation:
    return AIInterpretation(
        intent=AssistantIntent(
            business_id="business-001",
            intent_type="business_task",
            instruction="Create an appointment.",
        ),
        action=AssistantAction(
            business_id="business-001",
            action_type="create",
            target="appointment",
            instruction="Create an appointment.",
        ),
    )


def test_orchestrator_executes_interpreted_action():
    processor = Mock()
    executor = Mock()

    processor.process.return_value = make_interpretation()
    executor.execute.return_value = "Appointment creation requested."

    orchestrator = AssistantOrchestrator(
        business=make_business(),
        processor=processor,
        executor=executor,
    )

    message = AssistantMessage(
        business_id="business-001",
        content="Please create an appointment.",
    )

    result = orchestrator.handle(message)

    assert result == AssistantResponse(
        business_id="business-001",
        assistant_name="Business Assistant",
        message="Appointment creation requested.",
    )

    processor.process.assert_called_once_with(message)
    executor.execute.assert_called_once_with(
        make_interpretation().action,
        tenant=None,
    )


def test_orchestrator_rejects_interpretation_for_another_business():
    processor = Mock()
    executor = Mock()

    interpretation = AIInterpretation(
        intent=AssistantIntent(
            business_id="business-999",
            intent_type="business_task",
            instruction="Create an appointment.",
        ),
        action=AssistantAction(
            business_id="business-999",
            action_type="create",
            target="appointment",
            instruction="Create an appointment.",
        ),
    )

    processor.process.return_value = interpretation

    orchestrator = AssistantOrchestrator(
        business=make_business(),
        processor=processor,
        executor=executor,
    )

    message = AssistantMessage(
        business_id="business-001",
        content="Please create an appointment.",
    )

    with pytest.raises(ValueError):
        orchestrator.handle(message)

    executor.execute.assert_not_called()

def test_orchestrator_does_not_return_success_when_execution_fails():
    processor = Mock()
    executor = Mock()

    processor.process.return_value = make_interpretation()
    executor.execute.side_effect = RuntimeError("Appointment service unavailable")

    orchestrator = AssistantOrchestrator(
        business=make_business(),
        processor=processor,
        executor=executor,
    )

    message = AssistantMessage(
        business_id="business-001",
        content="Please create an appointment.",
    )

    with pytest.raises(RuntimeError, match="Appointment service unavailable"):
        orchestrator.handle(message)

    processor.process.assert_called_once_with(message)
    executor.execute.assert_called_once_with(
        make_interpretation().action,
        tenant=None,
    )


def make_tenant(
    business_id: str = "business-001",
) -> "TenantContext":
    from app.identity.models import AuthenticatedPrincipal, UserRole
    from app.identity.tenant import TenantContext

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


def test_orchestrator_forwards_authenticated_tenant_to_executor():
    processor = Mock()
    executor = Mock()

    interpretation = make_interpretation()
    processor.process.return_value = interpretation
    executor.execute.return_value = "Appointment creation requested."

    orchestrator = AssistantOrchestrator(
        business=make_business(),
        processor=processor,
        executor=executor,
    )

    message = AssistantMessage(
        business_id="business-001",
        content="Please create an appointment.",
    )
    tenant = make_tenant()

    result = orchestrator.handle(
        message,
        tenant=tenant,
    )

    assert result == AssistantResponse(
        business_id="business-001",
        assistant_name="Business Assistant",
        message="Appointment creation requested.",
    )

    executor.execute.assert_called_once_with(
        interpretation.action,
        tenant=tenant,
    )


def test_orchestrator_rejects_wrong_execution_tenant_before_processing():
    processor = Mock()
    executor = Mock()

    orchestrator = AssistantOrchestrator(
        business=make_business(),
        processor=processor,
        executor=executor,
    )

    message = AssistantMessage(
        business_id="business-001",
        content="Please create an appointment.",
    )
    wrong_tenant = make_tenant("business-999")

    with pytest.raises(
        ValueError,
        match="Execution tenant does not belong to this message business",
    ):
        orchestrator.handle(
            message,
            tenant=wrong_tenant,
        )

    processor.process.assert_not_called()
    executor.execute.assert_not_called()


def test_orchestrator_rejects_invalid_tenant_before_processing():
    processor = Mock()
    executor = Mock()

    orchestrator = AssistantOrchestrator(
        business=make_business(),
        processor=processor,
        executor=executor,
    )

    message = AssistantMessage(
        business_id="business-001",
        content="Please create an appointment.",
    )

    with pytest.raises(
        TypeError,
        match="tenant must be a TenantContext or None",
    ):
        orchestrator.handle(
            message,
            tenant=object(),
        )

    processor.process.assert_not_called()
    executor.execute.assert_not_called()


def test_orchestrator_preserves_existing_web_execution_without_tenant():
    processor = Mock()
    executor = Mock()

    processor.process.return_value = make_interpretation()
    executor.execute.return_value = "Appointment creation requested."

    orchestrator = AssistantOrchestrator(
        business=make_business(),
        processor=processor,
        executor=executor,
    )

    message = AssistantMessage(
        business_id="business-001",
        content="Please create an appointment.",
    )

    result = orchestrator.handle(message)

    assert result.message == "Appointment creation requested."

    executor.execute.assert_called_once_with(
        make_interpretation().action,
        tenant=None,
    )
