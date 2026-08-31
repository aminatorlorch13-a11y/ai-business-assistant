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
        make_interpretation().action
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
