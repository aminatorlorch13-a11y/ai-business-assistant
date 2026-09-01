from unittest.mock import Mock

import pytest

from app.assistant.action import AssistantAction
from app.assistant.intent import AssistantIntent
from app.assistant.interpretation import AIInterpretation
from app.assistant.message import AssistantMessage
from app.assistant.processor import AssistantProcessor
from app.assistant.interpretation_validator import AIInterpretationValidator
from app.assistant.response import AssistantResponse
from app.ai.provider import AIProvider


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
    provider = Mock(spec=AIProvider)
    validator = Mock(spec=AIInterpretationValidator)

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
    provider = Mock(spec=AIProvider)
    validator = Mock(spec=AIInterpretationValidator)

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


def test_processor_rejects_invalid_provider_dependency():
    with pytest.raises(TypeError, match="ai_provider"):
        AssistantProcessor(
            ai_provider=object(),
            validator=AIInterpretationValidator(),
        )


def test_processor_rejects_invalid_validator_dependency():
    with pytest.raises(TypeError, match="validator"):
        AssistantProcessor(
            ai_provider=Mock(spec=AIProvider),
            validator=object(),
        )


def test_processor_rejects_non_message_input():
    provider = Mock(spec=AIProvider)
    validator = Mock(spec=AIInterpretationValidator)

    processor = AssistantProcessor(
        ai_provider=provider,
        validator=validator,
    )

    with pytest.raises(TypeError, match="message"):
        processor.process("not a message")

    provider.interpret.assert_not_called()
    validator.validate.assert_not_called()


def test_processor_rejects_provider_returning_wrong_type():
    provider = Mock(spec=AIProvider)
    validator = Mock(spec=AIInterpretationValidator)

    provider.interpret.return_value = {
        "intent_type": "business_task",
    }

    processor = AssistantProcessor(
        ai_provider=provider,
        validator=validator,
    )

    message = AssistantMessage(
        business_id="business-001",
        content="Please create an appointment.",
    )

    with pytest.raises(TypeError, match="AI provider"):
        processor.process(message)

    validator.validate.assert_not_called()


def test_processor_rejects_validator_returning_wrong_type():
    provider = Mock(spec=AIProvider)
    validator = Mock(spec=AIInterpretationValidator)

    interpretation = make_interpretation()

    provider.interpret.return_value = interpretation
    validator.validate.return_value = {
        "invalid": "interpretation",
    }

    processor = AssistantProcessor(
        ai_provider=provider,
        validator=validator,
    )

    message = AssistantMessage(
        business_id="business-001",
        content="Please create an appointment.",
    )

    with pytest.raises(TypeError, match="validator"):
        processor.process(message)
