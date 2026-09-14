from app.ai.context import AIContext
from app.ai.rule_based_provider import RuleBasedAIProvider
from app.assistant.message import AssistantMessage
from app.memory.context import MemoryContext


def make_context(business_id: str = "business-001") -> AIContext:
    return AIContext(
        memory_context=MemoryContext(
            business_id=business_id,
            memories=(),
        )
    )


def test_provider_interprets_create_appointment_request():
    provider = RuleBasedAIProvider()

    message = AssistantMessage(
        business_id="business-001",
        content="Please create an appointment.",
    )

    interpretation = provider.interpret(
        message,
        make_context(),
    )

    assert interpretation.intent.intent_type == "business_task"
    assert interpretation.intent.business_id == "business-001"

    assert interpretation.action.action_type == "create"
    assert interpretation.action.target == "appointment"
    assert interpretation.action.business_id == "business-001"


def test_provider_returns_none_action_for_unsupported_request():
    provider = RuleBasedAIProvider()

    message = AssistantMessage(
        business_id="business-001",
        content="What is the weather today?",
    )

    interpretation = provider.interpret(
        message,
        make_context(),
    )

    assert interpretation.intent.intent_type == "general_question"
    assert interpretation.action.action_type == "none"
    assert interpretation.action.business_id == "business-001"


def test_provider_requires_context():
    provider = RuleBasedAIProvider()

    message = AssistantMessage(
        business_id="business-001",
        content="Please create an appointment.",
    )

    try:
        provider.interpret(message)  # type: ignore[call-arg]
    except TypeError:
        pass
    else:
        raise AssertionError(
            "RuleBasedAIProvider must not support context-free interpretation."
        )


def test_provider_rejects_wrong_business_context():
    provider = RuleBasedAIProvider()

    message = AssistantMessage(
        business_id="business-001",
        content="Please create an appointment.",
    )

    try:
        provider.interpret(
            message,
            make_context("business-999"),
        )
    except (ValueError, TypeError):
        pass
    else:
        raise AssertionError(
            "Provider must reject cross-business AIContext."
        )
