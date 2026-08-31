from app.ai.rule_based_provider import RuleBasedAIProvider
from app.assistant.message import AssistantMessage


def test_provider_interprets_create_appointment_request():
    provider = RuleBasedAIProvider()

    message = AssistantMessage(
        business_id="business-001",
        content="Please create an appointment.",
    )

    interpretation = provider.interpret(message)

    assert interpretation.intent.intent_type == "business_task"
    assert interpretation.intent.business_id == "business-001"

    assert interpretation.action.action_type == "create"
    assert interpretation.action.target == "appointment"
    assert interpretation.action.business_id == "business-001"


def test_provider_returns_none_for_unsupported_request():
    provider = RuleBasedAIProvider()

    message = AssistantMessage(
        business_id="business-001",
        content="What is the weather today?",
    )

    interpretation = provider.interpret(message)

    assert interpretation.intent.intent_type == "general_question"
    assert interpretation.action.action_type == "none"
    assert interpretation.action.business_id == "business-001"
