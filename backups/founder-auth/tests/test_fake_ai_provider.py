from app.ai.fake_provider import FakeAIProvider
from app.assistant.message import AssistantMessage


def test_fake_provider_returns_interpretation():
    provider = FakeAIProvider()

    message = AssistantMessage(
        business_id="business-001",
        content="Please create an appointment.",
    )

    interpretation = provider.interpret(message)

    assert interpretation.intent.business_id == "business-001"
    assert interpretation.action.business_id == "business-001"
    assert interpretation.action.action_type == "create"
    assert interpretation.action.target == "appointment"
