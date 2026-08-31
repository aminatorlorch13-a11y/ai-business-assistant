import pytest

from app.assistant.action import AssistantAction
from app.trust.action_safety import ActionSafetyPolicy


def make_action(action_type: str, target: str = "appointment") -> AssistantAction:
    return AssistantAction(
        business_id="business-001",
        action_type=action_type,
        target=target,
        instruction="Perform the requested operation.",
    )


def test_none_action_is_safe():
    policy = ActionSafetyPolicy()

    assert policy.requires_confirmation(make_action("none")) is False


def test_create_appointment_requires_confirmation():
    policy = ActionSafetyPolicy()

    assert policy.requires_confirmation(
        make_action("create", "appointment")
    ) is True


def test_update_appointment_requires_confirmation():
    policy = ActionSafetyPolicy()

    assert policy.requires_confirmation(
        make_action("update", "appointment")
    ) is True


def test_delete_requires_confirmation():
    policy = ActionSafetyPolicy()

    assert policy.requires_confirmation(
        make_action("delete", "appointment")
    ) is True


def test_policy_can_allow_automatic_create():
    policy = ActionSafetyPolicy(
        require_confirmation_for_create=False,
    )

    assert policy.requires_confirmation(
        make_action("create", "appointment")
    ) is False


def test_policy_rejects_unknown_action_type():
    policy = ActionSafetyPolicy()

    action = make_action("none")
    object.__setattr__(action, "action_type", "unknown")

    with pytest.raises(ValueError):
        policy.requires_confirmation(action)
