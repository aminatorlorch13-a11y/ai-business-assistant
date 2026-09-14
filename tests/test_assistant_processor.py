from app.memory.context import MemoryContextBuilder
from app.memory.context import MemoryContext
from app.ai.context import AIContext
from unittest.mock import Mock

from app.assistant.action import AssistantAction
from app.assistant.intent import AssistantIntent
from app.assistant.interpretation import AIInterpretation
from app.assistant.interpretation_validator import AIInterpretationValidator
from app.assistant.message import AssistantMessage
from app.ai.provider import AIProvider
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
    provider = Mock(spec=AIProvider)
    expected_interpretation = make_interpretation()
    provider.interpret.return_value = expected_interpretation

    memory_context_builder = Mock(spec=MemoryContextBuilder)
    memory_context_builder.build.return_value = MemoryContext(
        business_id="business-001",
        memories=(),
    )

    processor = AssistantProcessor(
        ai_provider=provider,
        validator=AIInterpretationValidator(),
        memory_context_builder=memory_context_builder,
    )

    message = AssistantMessage(
        business_id="business-001",
        content="Please create an appointment.",
    )

    result = processor.process(message)

    assert result == expected_interpretation
    provider.interpret.assert_called_once()
    called_message, called_context = provider.interpret.call_args.args

    assert called_message == message
    assert isinstance(called_context, AIContext)
    assert called_context.memory_context == MemoryContext(
        business_id="business-001",
        memories=(),
    )
    assert called_context.conversation_history.is_empty
    assert called_context.automation_context is None
