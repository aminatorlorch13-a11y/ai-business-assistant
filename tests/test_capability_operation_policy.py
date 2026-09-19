import pytest

from app.assistant.capability import Capability
from app.trust.capability_operation_policy import (
    CapabilityOperationPolicy,
)


def make_policy() -> CapabilityOperationPolicy:
    return CapabilityOperationPolicy(
        confirmation_by_operation={
            Capability.CALCULATOR: {
                "calculate": False,
            },
            Capability.CALENDAR: {
                "create_event": True,
                "update_event": True,
                "delete_event": True,
            },
        }
    )


def test_policy_requires_confirmation_for_registered_mutating_operation():
    policy = make_policy()

    assert policy.requires_confirmation(
        Capability.CALENDAR,
        "create_event",
    ) is True


def test_policy_requires_confirmation_for_registered_update_operation():
    policy = make_policy()

    assert policy.requires_confirmation(
        Capability.CALENDAR,
        "update_event",
    ) is True


def test_policy_requires_confirmation_for_registered_delete_operation():
    policy = make_policy()

    assert policy.requires_confirmation(
        Capability.CALENDAR,
        "delete_event",
    ) is True


def test_policy_does_not_require_confirmation_for_registered_safe_operation():
    policy = make_policy()

    assert policy.requires_confirmation(
        Capability.CALCULATOR,
        "calculate",
    ) is False


def test_policy_rejects_unknown_capability():
    policy = make_policy()

    with pytest.raises(LookupError):
        policy.requires_confirmation(
            Capability.MEMORY,
            "remember",
        )


def test_policy_rejects_unknown_operation():
    policy = make_policy()

    with pytest.raises(LookupError):
        policy.requires_confirmation(
            Capability.CALENDAR,
            "fly_to_moon",
        )


def test_policy_normalizes_operation_names():
    policy = make_policy()

    assert policy.requires_confirmation(
        Capability.CALENDAR,
        " create_event ",
    ) is True


def test_policy_rejects_invalid_capability():
    policy = make_policy()

    with pytest.raises(TypeError):
        policy.requires_confirmation(
            "calendar",
            "create_event",
        )


def test_policy_rejects_invalid_operation_type():
    policy = make_policy()

    with pytest.raises(TypeError):
        policy.requires_confirmation(
            Capability.CALENDAR,
            123,
        )


def test_policy_rejects_empty_operation():
    policy = make_policy()

    with pytest.raises(ValueError):
        policy.requires_confirmation(
            Capability.CALENDAR,
            "   ",
        )


def test_policy_rejects_invalid_configuration_capability():
    with pytest.raises(TypeError):
        CapabilityOperationPolicy(
            confirmation_by_operation={
                "calendar": {
                    "create_event": True,
                }
            }
        )


def test_policy_rejects_invalid_configuration_operations():
    with pytest.raises(TypeError):
        CapabilityOperationPolicy(
            confirmation_by_operation={
                Capability.CALENDAR: (
                    ["create_event"]
                ),
            }
        )


def test_policy_rejects_invalid_confirmation_value():
    with pytest.raises(TypeError):
        CapabilityOperationPolicy(
            confirmation_by_operation={
                Capability.CALENDAR: {
                    "create_event": "yes",
                }
            }
        )


def test_policy_does_not_use_ai_reversible_flag():
    policy = make_policy()

    assert policy.requires_confirmation(
        Capability.CALENDAR,
        "create_event",
    ) is True

    assert policy.requires_confirmation(
        Capability.CALCULATOR,
        "calculate",
    ) is False
