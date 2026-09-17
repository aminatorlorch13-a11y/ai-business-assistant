from unittest.mock import Mock

import pytest

from app.ai.context import AIContext
from app.ai.interpreting_provider import InterpretingAIProvider
from app.ai.raw_provider import RawAIProvider
from app.assistant.message import AssistantMessage
from app.memory.context import MemoryContext


def make_message() -> AssistantMessage:
    return AssistantMessage(
        business_id="business-001",
        content="Please create an appointment.",
    )


def make_context(business_id: str = "business-001") -> AIContext:
    return AIContext(
        memory_context=MemoryContext(
            business_id=business_id,
            memories=(),
        )
    )


def make_raw_response() -> dict[str, object]:
    return {
        "intent_type": "business_task",
        "instruction": "Create an appointment.",
        "action_type": "create",
        "target": "appointment",
        "action_instruction": "Create an appointment.",
    }


def test_interpreting_provider_passes_ai_context_to_raw_provider():
    raw_provider = Mock(spec=RawAIProvider)
    raw_provider.generate.return_value = make_raw_response()

    provider = InterpretingAIProvider(raw_provider)

    message = make_message()
    context = make_context()

    result = provider.interpret(message, context)

    assert result.intent.business_id == "business-001"
    assert result.intent.intent_type == "business_task"
    assert result.action.business_id == "business-001"
    assert result.action.action_type == "create"
    assert result.action.target == "appointment"

    raw_provider.generate.assert_called_once_with(
        message,
        context,
    )


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
        provider.interpret(
            make_message(),
            make_context(),
        )

    raw_provider.generate.assert_called_once()


def test_interpreting_provider_passes_business_id_to_parser():
    raw_provider = Mock(spec=RawAIProvider)
    raw_provider.generate.return_value = make_raw_response()

    parser = Mock()

    provider = InterpretingAIProvider(
        raw_provider=raw_provider,
        parser=parser,
    )

    message = make_message()
    context = make_context()

    provider.interpret(message, context)

    parser.parse.assert_called_once_with(
        make_raw_response(),
        business_id="business-001",
    )


def test_interpreting_provider_implements_ai_provider():
    from app.ai.provider import AIProvider

    assert issubclass(InterpretingAIProvider, AIProvider)


def test_interpreting_provider_requires_context():
    raw_provider = Mock(spec=RawAIProvider)
    provider = InterpretingAIProvider(raw_provider)

    with pytest.raises(TypeError):
        provider.interpret(make_message())  # type: ignore[call-arg]

    raw_provider.generate.assert_not_called()


def test_interpreting_provider_rejects_wrong_context_type():
    raw_provider = Mock(spec=RawAIProvider)
    provider = InterpretingAIProvider(raw_provider)

    with pytest.raises(TypeError):
        provider.interpret(
            make_message(),
            object(),  # type: ignore[arg-type]
        )

    raw_provider.generate.assert_not_called()


def test_interpreting_provider_rejects_cross_business_context():
    raw_provider = Mock(spec=RawAIProvider)
    provider = InterpretingAIProvider(raw_provider)

    with pytest.raises((ValueError, TypeError)):
        provider.interpret(
            make_message(),
            make_context("business-999"),
        )

    raw_provider.generate.assert_not_called()


def test_interpreting_provider_wraps_raw_provider_failure():
    from app.ai.errors import AIProviderError

    raw_provider = Mock(spec=RawAIProvider)
    raw_provider.generate.side_effect = RuntimeError(
        "Provider unavailable"
    )

    provider = InterpretingAIProvider(raw_provider)

    with pytest.raises(AIProviderError, match="AI provider failed"):
        provider.interpret(
            make_message(),
            make_context(),
        )


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
        provider.interpret(
            make_message(),
            make_context(),
        )


def test_interpreting_provider_does_not_call_parser_when_raw_provider_fails():
    from app.ai.errors import AIProviderError

    raw_provider = Mock(spec=RawAIProvider)
    raw_provider.generate.side_effect = RuntimeError(
        "Network failure"
    )

    parser = Mock()

    provider = InterpretingAIProvider(
        raw_provider=raw_provider,
        parser=parser,
    )

    with pytest.raises(AIProviderError):
        provider.interpret(
            make_message(),
            make_context(),
        )

    parser.parse.assert_not_called()
