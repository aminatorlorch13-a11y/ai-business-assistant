from unittest.mock import Mock

import pytest

from app.ai.context import AIContext
from app.ai.structured_provider import StructuredAIProvider
from app.assistant.ai_result import AIResult
from app.assistant.conversation import ConversationHistory
from app.assistant.message import AssistantMessage
from app.assistant.structured_processor import StructuredAssistantProcessor
from app.automation.context import AutomationContext
from app.memory.context import MemoryContext
from app.memory.context import MemoryContextBuilder


def make_message(
    business_id: str = "business-001",
) -> AssistantMessage:
    return AssistantMessage(
        business_id=business_id,
        content="What is 25 times 4?",
    )


def make_result() -> AIResult:
    return AIResult(response="The answer is 100.")


def make_memory_context(
    business_id: str = "business-001",
) -> MemoryContext:
    return MemoryContext(
        business_id=business_id,
        memories=(),
    )


def make_builder() -> Mock:
    builder = Mock(spec=MemoryContextBuilder)
    builder.build.return_value = make_memory_context()
    return builder


class ContextAwareStructuredProvider(StructuredAIProvider):
    def __init__(self, result: AIResult) -> None:
        self.result = result
        self.message = None
        self.context = None

    def generate(
        self,
        message: AssistantMessage,
        context: AIContext,
    ) -> AIResult:
        self.message = message
        self.context = context
        return self.result


def test_structured_processor_returns_ai_result():
    provider = ContextAwareStructuredProvider(make_result())
    builder = make_builder()

    processor = StructuredAssistantProcessor(
        ai_provider=provider,
        memory_context_builder=builder,
    )

    message = make_message()

    result = processor.process(message)

    assert result == make_result()
    assert provider.message == message
    assert isinstance(provider.context, AIContext)
    assert provider.context.memory_context == make_memory_context()


def test_structured_processor_requires_memory_context_builder():
    provider = ContextAwareStructuredProvider(make_result())

    processor = StructuredAssistantProcessor(
        ai_provider=provider,
    )

    with pytest.raises(
        RuntimeError,
        match="MemoryContextBuilder is required",
    ):
        processor.process(make_message())

    assert provider.message is None


def test_structured_processor_rejects_invalid_provider_dependency():
    with pytest.raises(TypeError, match="StructuredAIProvider"):
        StructuredAssistantProcessor(
            ai_provider=object(),
            memory_context_builder=make_builder(),
        )


def test_structured_processor_rejects_invalid_memory_builder():
    provider = ContextAwareStructuredProvider(make_result())

    with pytest.raises(TypeError, match="MemoryContextBuilder"):
        StructuredAssistantProcessor(
            ai_provider=provider,
            memory_context_builder=object(),
        )


def test_structured_processor_rejects_non_message_input():
    provider = ContextAwareStructuredProvider(make_result())
    processor = StructuredAssistantProcessor(
        ai_provider=provider,
        memory_context_builder=make_builder(),
    )

    with pytest.raises(TypeError, match="message"):
        processor.process("not a message")

    assert provider.message is None


def test_structured_processor_rejects_wrong_provider_result():
    class WrongResultProvider(StructuredAIProvider):
        def generate(
            self,
            message: AssistantMessage,
            context: AIContext,
        ) -> AIResult:
            return {"response": "not an AIResult"}  # type: ignore[return-value]

    processor = StructuredAssistantProcessor(
        ai_provider=WrongResultProvider(),
        memory_context_builder=make_builder(),
    )

    with pytest.raises(TypeError, match="AIResult"):
        processor.process(make_message())


def test_structured_processor_preserves_conversation_history():
    provider = ContextAwareStructuredProvider(make_result())
    builder = make_builder()

    history = ConversationHistory(business_id="business-001")

    processor = StructuredAssistantProcessor(
        ai_provider=provider,
        memory_context_builder=builder,
    )

    processor.process(
        make_message(),
        conversation_history=history,
    )

    assert provider.context.conversation_history is history


def test_structured_processor_preserves_automation_context():
    provider = ContextAwareStructuredProvider(make_result())
    builder = make_builder()

    automation_context = AutomationContext(
        business_id="business-001",
        event_type="customer_request",
        payload={
            "instruction": "__import__('os').system('touch /tmp/pwned')",
        },
    )

    processor = StructuredAssistantProcessor(
        ai_provider=provider,
        memory_context_builder=builder,
    )

    processor.process(
        make_message(),
        automation_context=automation_context,
    )

    assert provider.context.automation_context is automation_context
    assert (
        provider.context.automation_context.payload["instruction"]
        == "__import__('os').system('touch /tmp/pwned')"
    )


def test_structured_processor_rejects_cross_business_history():
    provider = ContextAwareStructuredProvider(make_result())
    processor = StructuredAssistantProcessor(
        ai_provider=provider,
        memory_context_builder=make_builder(),
    )

    history = ConversationHistory(business_id="business-999")

    with pytest.raises(ValueError, match="does not belong"):
        processor.process(
            make_message("business-001"),
            conversation_history=history,
        )

    assert provider.message is None


def test_structured_processor_rejects_cross_business_automation_context():
    provider = ContextAwareStructuredProvider(make_result())
    processor = StructuredAssistantProcessor(
        ai_provider=provider,
        memory_context_builder=make_builder(),
    )

    automation_context = AutomationContext(
        business_id="business-999",
        event_type="customer_request",
        payload={},
    )

    with pytest.raises(ValueError, match="does not belong"):
        processor.process(
            make_message("business-001"),
            automation_context=automation_context,
        )

    assert provider.message is None


def test_structured_processor_passes_empty_context_defaults():
    provider = ContextAwareStructuredProvider(make_result())

    processor = StructuredAssistantProcessor(
        ai_provider=provider,
        memory_context_builder=make_builder(),
    )

    processor.process(make_message())

    assert provider.context.conversation_history.is_empty
    assert provider.context.automation_context is None


def test_structured_processor_does_not_construct_execution_request():
    provider = ContextAwareStructuredProvider(make_result())

    processor = StructuredAssistantProcessor(
        ai_provider=provider,
        memory_context_builder=make_builder(),
    )

    result = processor.process(make_message())

    assert isinstance(result, AIResult)
    assert not hasattr(result, "business_id")
    assert not hasattr(result, "handler")
    assert not hasattr(result, "credentials")
    assert not hasattr(result, "execution")
