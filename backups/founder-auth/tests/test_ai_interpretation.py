import pytest

from app.assistant.action import AssistantAction
from app.assistant.intent import AssistantIntent
from app.assistant.interpretation import AIInterpretation


def make_intent() -> AssistantIntent:
    return AssistantIntent(
        business_id="business-001",
        intent_type="business_task",
        instruction="Create an appointment.",
    )


def make_action(business_id: str = "business-001") -> AssistantAction:
    return AssistantAction(
        business_id=business_id,
        action_type="create",
        target="appointment",
        instruction="Create an appointment.",
    )


def test_interpretation_accepts_matching_business():
    interpretation = AIInterpretation(
        intent=make_intent(),
        action=make_action(),
    )

    assert interpretation.intent.business_id == "business-001"
    assert interpretation.action.business_id == "business-001"


def test_interpretation_rejects_mismatched_business():
    with pytest.raises(ValueError):
        AIInterpretation(
            intent=make_intent(),
            action=make_action("business-002"),
        )
