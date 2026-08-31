import pytest

from app.assistant.intent import AssistantIntent


def test_intent_accepts_valid_data():
    intent = AssistantIntent(
        business_id="business-001",
        intent_type="business_task",
        instruction="Check tomorrow's appointments.",
    )

    assert intent.business_id == "business-001"
    assert intent.intent_type == "business_task"
    assert intent.instruction == "Check tomorrow's appointments."


def test_intent_rejects_unknown_type():
    with pytest.raises(ValueError):
        AssistantIntent(
            business_id="business-001",
            intent_type="do_anything",
            instruction="Do something.",
        )


def test_intent_rejects_empty_instruction():
    with pytest.raises(ValueError):
        AssistantIntent(
            business_id="business-001",
            intent_type="business_task",
            instruction="",
        )


def test_intent_rejects_empty_business_id():
    with pytest.raises(ValueError):
        AssistantIntent(
            business_id="",
            intent_type="business_task",
            instruction="Check appointments.",
        )
