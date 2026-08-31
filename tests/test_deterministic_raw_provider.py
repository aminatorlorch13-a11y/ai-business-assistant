from app.ai.deterministic_raw_provider import DeterministicRawAIProvider
from app.assistant.message import AssistantMessage


def test_provider_generates_create_appointment_response():
    provider = DeterministicRawAIProvider()

    message = AssistantMessage(
        business_id="business-001",
        content="Please create an appointment.",
    )

    result = provider.generate(message)

    assert result["intent_type"] == "business_task"
    assert result["action_type"] == "create"
    assert result["target"] == "appointment"


def test_provider_generates_none_action_for_unsupported_request():
    provider = DeterministicRawAIProvider()

    message = AssistantMessage(
        business_id="business-001",
        content="What is the weather today?",
    )

    result = provider.generate(message)

    assert result["intent_type"] == "general_question"
    assert result["action_type"] == "none"
    assert result["target"] == "assistant"
