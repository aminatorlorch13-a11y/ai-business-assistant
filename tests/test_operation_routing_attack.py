import pytest

from app.assistant.action import AssistantAction
from app.services.assistant_conversation_operation import (
    AssistantConversationOperation,
)
from app.services.target_routed_operation import TargetRoutedOperation
from app.services.business_operation import BusinessOperation


def make_action(
    *,
    target: str = "assistant",
    instruction: str = "Hello",
) -> AssistantAction:
    return AssistantAction(
        business_id="business-1",
        action_type="none",
        target=target,
        instruction=instruction,
    )


class RecordingOperation(BusinessOperation):
    def __init__(self) -> None:
        self.calls = []

    def execute(self, action: AssistantAction) -> str:
        self.calls.append(action)
        return f"handled:{action.target}"


def test_assistant_operation_accepts_only_assistant_target():
    operation = AssistantConversationOperation()

    result = operation.execute(make_action(target="assistant"))

    assert result == "Hello"


@pytest.mark.parametrize(
    "target",
    [
        "appointment",
        "customer",
        "admin",
        "",
        " assistant",
        "assistant ",
        "ASSISTANT",
    ],
)
def test_assistant_operation_rejects_non_exact_assistant_targets(target):
    operation = AssistantConversationOperation()

    with pytest.raises(ValueError):
        operation.execute(make_action(target=target))


def test_assistant_operation_returns_instruction_without_rewriting_it():
    operation = AssistantConversationOperation()
    instruction = "This is a natural conversational response with punctuation!"

    assert (
        operation.execute(
            make_action(
                target="assistant",
                instruction=instruction,
            )
        )
        == instruction
    )


def test_target_router_dispatches_to_registered_operation():
    assistant_operation = RecordingOperation()

    router = TargetRoutedOperation(
        {
            "assistant": assistant_operation,
        }
    )

    action = make_action(target="assistant")

    result = router.execute(action)

    assert result == "handled:assistant"
    assert assistant_operation.calls == [action]


def test_target_router_does_not_execute_unregistered_target():
    operation = RecordingOperation()
    router = TargetRoutedOperation({"assistant": operation})

    with pytest.raises(ValueError, match="No operation registered"):
        router.execute(make_action(target="appointment"))

    assert operation.calls == []


def test_target_router_routes_multiple_targets_independently():
    assistant_operation = RecordingOperation()
    appointment_operation = RecordingOperation()

    router = TargetRoutedOperation(
        {
            "assistant": assistant_operation,
            "appointment": appointment_operation,
        }
    )

    assistant_action = make_action(target="assistant")
    appointment_action = make_action(target="appointment")

    assert router.execute(assistant_action) == "handled:assistant"
    assert router.execute(appointment_action) == "handled:appointment"

    assert assistant_operation.calls == [assistant_action]
    assert appointment_operation.calls == [appointment_action]


def test_target_router_defensively_copies_operation_mapping():
    operation = RecordingOperation()
    registrations = {"assistant": operation}

    router = TargetRoutedOperation(registrations)

    registrations.clear()

    assert router.execute(make_action(target="assistant")) == "handled:assistant"


def test_target_router_rejects_invalid_operation_registration():
    with pytest.raises(TypeError):
        TargetRoutedOperation(
            {
                "assistant": object(),
            }
        )


def test_target_router_rejects_empty_registration_key():
    operation = RecordingOperation()

    with pytest.raises(ValueError):
        TargetRoutedOperation(
            {
                "": operation,
            }
        )


def test_target_router_does_not_fall_back_to_another_operation():
    assistant_operation = RecordingOperation()
    appointment_operation = RecordingOperation()

    router = TargetRoutedOperation(
        {
            "assistant": assistant_operation,
            "appointment": appointment_operation,
        }
    )

    with pytest.raises(ValueError):
        router.execute(make_action(target="unknown"))

    assert assistant_operation.calls == []
    assert appointment_operation.calls == []


def test_target_router_rejects_whitespace_only_registration_key():
    operation = RecordingOperation()

    with pytest.raises(ValueError):
        TargetRoutedOperation(
            {
                "   ": operation,
            }
        )
