from unittest.mock import Mock

import pytest

from app.ai.capability_response_parser import AICapabilityResponseParser
from app.ai.context import AIContext
from app.ai.errors import AIProviderError
from app.ai.raw_provider import RawAIProvider
from app.ai.structured_provider import ParsedRawAIProvider, StructuredAIProvider
from app.assistant.ai_result import AIResult
from app.assistant.message import AssistantMessage
from app.memory.context import MemoryContext


def make_context() -> AIContext:
    return AIContext(
        memory_context=MemoryContext(
            business_id="business-001",
            memories=(),
        )
    )


def make_message() -> AssistantMessage:
    return AssistantMessage(
        business_id="business-001",
        content="What is 25 times 4?",
    )


def make_raw_response() -> dict[str, object]:
    return {
        "response": "The answer is 100.",
        "capability_requests": [
            {
                "capability": "calculator",
                "operation": "calculate",
                "arguments": {"expression": "25 * 4"},
                "reason": "The user requested a calculation.",
                "reversible": True,
            }
        ],
    }


def test_structured_provider_is_abstract():
    assert issubclass(StructuredAIProvider, object)

    with pytest.raises(TypeError):
        StructuredAIProvider()


def test_parsed_raw_provider_requires_raw_provider():
    with pytest.raises(TypeError, match="raw_provider"):
        ParsedRawAIProvider(object())


def test_parsed_raw_provider_requires_parser_type():
    raw_provider = Mock(spec=RawAIProvider)

    with pytest.raises(TypeError, match="parser"):
        ParsedRawAIProvider(
            raw_provider=raw_provider,
            parser=object(),
        )


def test_parsed_raw_provider_returns_ai_result():
    raw_provider = Mock(spec=RawAIProvider)
    raw_provider.generate.return_value = make_raw_response()

    provider = ParsedRawAIProvider(raw_provider=raw_provider)

    result = provider.generate(
        make_message(),
        make_context(),
    )

    assert isinstance(result, AIResult)
    assert result.response == "The answer is 100."
    assert len(result.capability_requests) == 1
    assert result.capability_requests[0].capability.value == "calculator"

    raw_provider.generate.assert_called_once()


def test_parsed_raw_provider_uses_supplied_parser():
    raw_provider = Mock(spec=RawAIProvider)
    raw_provider.generate.return_value = make_raw_response()

    parser = Mock(spec=AICapabilityResponseParser)
    expected = AIResult(response="Parsed.")

    parser.parse.return_value = expected

    provider = ParsedRawAIProvider(
        raw_provider=raw_provider,
        parser=parser,
    )

    result = provider.generate(
        make_message(),
        make_context(),
    )

    assert result is expected
    parser.parse.assert_called_once_with(make_raw_response())


def test_parsed_raw_provider_rejects_cross_business_context():
    raw_provider = Mock(spec=RawAIProvider)

    provider = ParsedRawAIProvider(raw_provider=raw_provider)

    message = make_message()

    context = AIContext(
        memory_context=MemoryContext(
            business_id="business-999",
            memories=(),
        )
    )

    with pytest.raises(ValueError, match="does not belong"):
        provider.generate(message, context)

    raw_provider.generate.assert_not_called()


def test_parsed_raw_provider_rejects_wrong_message_type():
    raw_provider = Mock(spec=RawAIProvider)
    provider = ParsedRawAIProvider(raw_provider=raw_provider)

    with pytest.raises(TypeError, match="message"):
        provider.generate("not a message", make_context())

    raw_provider.generate.assert_not_called()


def test_parsed_raw_provider_rejects_wrong_context_type():
    raw_provider = Mock(spec=RawAIProvider)
    provider = ParsedRawAIProvider(raw_provider=raw_provider)

    with pytest.raises(TypeError, match="context"):
        provider.generate(make_message(), "not context")

    raw_provider.generate.assert_not_called()


def test_parsed_raw_provider_rejects_non_mapping_provider_output():
    raw_provider = Mock(spec=RawAIProvider)
    raw_provider.generate.return_value = ["not", "mapping"]

    provider = ParsedRawAIProvider(raw_provider=raw_provider)

    with pytest.raises(TypeError, match="non-mapping"):
        provider.generate(make_message(), make_context())


def test_parsed_raw_provider_preserves_ai_provider_error():
    raw_provider = Mock(spec=RawAIProvider)
    expected = AIProviderError("provider unavailable")
    raw_provider.generate.side_effect = expected

    provider = ParsedRawAIProvider(raw_provider=raw_provider)

    with pytest.raises(AIProviderError) as exc_info:
        provider.generate(make_message(), make_context())

    assert exc_info.value is expected


def test_parsed_raw_provider_sanitizes_unexpected_provider_error():
    raw_provider = Mock(spec=RawAIProvider)
    raw_provider.generate.side_effect = RuntimeError(
        "secret transport details"
    )

    provider = ParsedRawAIProvider(raw_provider=raw_provider)

    with pytest.raises(AIProviderError, match="AI provider failed"):
        provider.generate(make_message(), make_context())


def test_parsed_raw_provider_does_not_execute_malicious_arguments():
    raw_provider = Mock(spec=RawAIProvider)
    raw_provider.generate.return_value = {
        "response": "I cannot execute that.",
        "capability_requests": [
            {
                "capability": "calculator",
                "operation": "calculate",
                "arguments": {
                    "expression": "__import__('os').system('touch /tmp/pwned')",
                },
                "reason": "Untrusted calculation expression.",
                "reversible": True,
            }
        ],
    }

    provider = ParsedRawAIProvider(raw_provider=raw_provider)

    result = provider.generate(make_message(), make_context())

    assert isinstance(result, AIResult)
    assert (
        result.capability_requests[0].arguments["expression"]
        == "__import__('os').system('touch /tmp/pwned')"
    )


def test_parser_remains_application_boundary():
    raw_provider = Mock(spec=RawAIProvider)
    raw_provider.generate.return_value = {
        "response": "No.",
        "capability_requests": [],
        "business_id": "business-001",
    }

    provider = ParsedRawAIProvider(raw_provider=raw_provider)

    with pytest.raises(ValueError, match="unknown fields"):
        provider.generate(make_message(), make_context())
