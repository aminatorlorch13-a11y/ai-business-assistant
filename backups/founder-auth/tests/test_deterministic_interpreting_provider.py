from app.ai.context import AIContext
from app.ai.deterministic_raw_provider import DeterministicRawAIProvider
from app.ai.interpreting_provider import InterpretingAIProvider
from app.assistant.message import AssistantMessage
from app.memory.context import MemoryContext


def make_context(business_id: str = "business-001") -> AIContext:
    return AIContext(
        memory_context=MemoryContext(
            business_id=business_id,
            memories=(),
        )
    )


def test_deterministic_provider_flows_through_interpreting_provider():
    provider = InterpretingAIProvider(
        raw_provider=DeterministicRawAIProvider(),
    )

    message = AssistantMessage(
        business_id="business-001",
        content="Please create an appointment.",
    )

    result = provider.interpret(
        message,
        make_context(),
    )

    assert result.intent.business_id == "business-001"
    assert result.intent.intent_type == "business_task"
    assert result.action.business_id == "business-001"
    assert result.action.action_type == "create"
    assert result.action.target == "appointment"


def test_deterministic_provider_flows_none_action_through_interpreting_provider():
    provider = InterpretingAIProvider(
        raw_provider=DeterministicRawAIProvider(),
    )

    message = AssistantMessage(
        business_id="business-001",
        content="What is the weather today?",
    )

    result = provider.interpret(
        message,
        make_context(),
    )

    assert result.intent.business_id == "business-001"
    assert result.intent.intent_type == "general_question"
    assert result.action.business_id == "business-001"
    assert result.action.action_type == "none"


def test_deterministic_raw_provider_receives_real_ai_context():
    raw_provider = DeterministicRawAIProvider()

    provider = InterpretingAIProvider(
        raw_provider=raw_provider,
    )

    message = AssistantMessage(
        business_id="business-001",
        content="Please create an appointment.",
    )

    context = make_context()

    result = provider.interpret(
        message,
        context,
    )

    assert result.intent.business_id == "business-001"
    assert context.memory_context.business_id == "business-001"
