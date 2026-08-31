from app.ai.deterministic_raw_provider import DeterministicRawAIProvider
from app.ai.interpreting_provider import InterpretingAIProvider
from app.assistant.message import AssistantMessage


def test_deterministic_provider_flows_through_interpreting_provider():
    provider = InterpretingAIProvider(
        raw_provider=DeterministicRawAIProvider(),
    )

    message = AssistantMessage(
        business_id="business-001",
        content="Please create an appointment.",
    )

    result = provider.interpret(message)

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

    result = provider.interpret(message)

    assert result.intent.intent_type == "general_question"
    assert result.action.action_type == "none"
