from unittest.mock import Mock

from app.assistant.action import AssistantAction
from app.assistant.intent import AssistantIntent
from app.assistant.interpretation import AIInterpretation
from app.assistant.interpretation_validator import AIInterpretationValidator
from app.assistant.message import AssistantMessage
from app.assistant.processor import AssistantProcessor


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


def test_processor_delegates_to_ai_provider():
    provider = Mock()
    expected_interpretation = make_interpretation()
    provider.interpret.return_value = expected_interpretation

    processor = AssistantProcessor(
        ai_provider=provider,
        validator=AIInterpretationValidator(),
    )

    message = AssistantMessage(
        business_id="business-001",
        content="Please create an appointment.",
    )

    result = processor.process(message)

    assert result == expected_interpretation
    provider.interpret.assert_called_once_with(message)
