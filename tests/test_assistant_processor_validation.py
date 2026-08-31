from unittest.mock import Mock

import pytest

from app.assistant.action import AssistantAction
from app.assistant.intent import AssistantIntent
from app.assistant.interpretation import AIInterpretation
from app.assistant.message import AssistantMessage
from app.assistant.processor import AssistantProcessor
from app.assistant.response import AssistantResponse


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


def test_processor_validates_ai_interpretation():
    provider = Mock()
    validator = Mock()

    interpretation = make_interpretation()

    provider.interpret.return_value = interpretation
    validator.validate.return_value = interpretation

    processor = AssistantProcessor(
        ai_provider=provider,
        validator=validator,
    )

    message = AssistantMessage(
        business_id="business-001",
        content="Please create an appointment.",
    )

    result = processor.process(message)

    assert result == interpretation

    provider.interpret.assert_called_once_with(message)
    validator.validate.assert_called_once_with(
        interpretation,
        business_id="business-001",
    )


def test_processor_rejects_invalid_ai_interpretation():
    provider = Mock()
    validator = Mock()

    interpretation = make_interpretation()

    provider.interpret.return_value = interpretation
    validator.validate.side_effect = ValueError(
        "Invalid AI interpretation."
    )

    processor = AssistantProcessor(
        ai_provider=provider,
        validator=validator,
    )

    message = AssistantMessage(
        business_id="business-001",
        content="Please create an appointment.",
    )

    with pytest.raises(ValueError):
        processor.process(message)

    provider.interpret.assert_called_once_with(message)
    validator.validate.assert_called_once()
