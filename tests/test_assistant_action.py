import pytest

from app.assistant.action import AssistantAction


def test_action_accepts_valid_data():
    action = AssistantAction(
        business_id="business-001",
        action_type="create",
        target="appointment",
        instruction="Create an appointment for the customer.",
    )

    assert action.business_id == "business-001"
    assert action.action_type == "create"
    assert action.target == "appointment"
    assert action.instruction == "Create an appointment for the customer."


def test_action_accepts_none_action():
    action = AssistantAction(
        business_id="business-001",
        action_type="none",
        target="conversation",
        instruction="No business action is required.",
    )

    assert action.action_type == "none"


def test_action_rejects_unknown_action_type():
    with pytest.raises(ValueError):
        AssistantAction(
            business_id="business-001",
            action_type="execute_everything",
            target="system",
            instruction="Do anything.",
        )


def test_action_rejects_empty_target():
    with pytest.raises(ValueError):
        AssistantAction(
            business_id="business-001",
            action_type="create",
            target="",
            instruction="Create something.",
        )
