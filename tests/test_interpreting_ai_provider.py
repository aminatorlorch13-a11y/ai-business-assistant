from unittest.mock import Mock

import pytest

from app.ai.interpreting_provider import InterpretingAIProvider
from app.ai.raw_provider import RawAIProvider
from app.assistant.message import AssistantMessage


def make_message() -> AssistantMessage:
    return AssistantMessage(
        business_id="business-001",
        content="Please create an appointment.",
    )


def make_raw_response() -> dict[str, object]:
    return {
        "intent_type": "business_task",
        "instruction": "Create an appointment.",
        "action_type": "create",
        "target": "appointment",
        "action_instruction": "Create an appointment.",
    }


def test_interpreting_provider_parses_raw_provider_output():
    raw_provider = Mock(spec=RawAIProvider)
    raw_provider.generate.return_value = make_raw_response()

    provider = InterpretingAIProvider(raw_provider)

    result = provider.interpret(make_message())

    assert result.intent.business_id == "business-001"
    assert result.intent.intent_type == "business_task"
    assert result.action.business_id == "business-001"
    assert result.action.action_type == "create"
    assert result.action.target == "appointment"

    raw_provider.generate.assert_called_once_with(make_message())


def test_interpreting_provider_rejects_invalid_raw_output():
    raw_provider = Mock(spec=RawAIProvider)
    raw_provider.generate.return_value = {
        "intent_type": "business_task",
        "instruction": "Create an appointment.",
        "action_type": "hack",
        "target": "appointment",
        "action_instruction": "Create an appointment.",
    }

    provider = InterpretingAIProvider(raw_provider)

    with pytest.raises(ValueError):
        provider.interpret(make_message())

    raw_provider.generate.assert_called_once_with(make_message())


def test_interpreting_provider_passes_business_id_to_parser():
    raw_provider = Mock(spec=RawAIProvider)
    raw_provider.generate.return_value = make_raw_response()

    parser = Mock()
    provider = InterpretingAIProvider(
        raw_provider=raw_provider,
        parser=parser,
    )

    provider.interpret(make_message())

    parser.parse.assert_called_once_with(
        make_raw_response(),
        business_id="business-001",
    )


def test_interpreting_provider_implements_ai_provider():
    from app.ai.provider import AIProvider

    assert issubclass(InterpretingAIProvider, AIProvider)

def test_interpreting_provider_wraps_raw_provider_failure():
    from app.ai.errors import AIProviderError

    raw_provider = Mock(spec=RawAIProvider)
    raw_provider.generate.side_effect = RuntimeError("Provider unavailable")

    provider = InterpretingAIProvider(raw_provider)

    with pytest.raises(AIProviderError, match="AI provider failed"):
        provider.interpret(make_message())


def test_interpreting_provider_preserves_parser_errors():
    raw_provider = Mock(spec=RawAIProvider)
    raw_provider.generate.return_value = {
        "intent_type": "business_task",
        "instruction": "Create an appointment.",
        "action_type": "hack",
        "target": "appointment",
        "action_instruction": "Create an appointment.",
    }

    provider = InterpretingAIProvider(raw_provider)

    with pytest.raises(ValueError):
        provider.interpret(make_message())


def test_interpreting_provider_does_not_call_parser_when_raw_provider_fails():
    from app.ai.errors import AIProviderError

    raw_provider = Mock(spec=RawAIProvider)
    raw_provider.generate.side_effect = RuntimeError("Network failure")

    parser = Mock()
    provider = InterpretingAIProvider(
        raw_provider=raw_provider,
        parser=parser,
    )

    with pytest.raises(AIProviderError):
        provider.interpret(make_message())

    parser.parse.assert_not_called()
