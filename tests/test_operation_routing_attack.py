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
        self.last_tenant = None

    def execute(self, action: AssistantAction, tenant=None) -> str:
        self.calls.append(action)
        self.last_tenant = tenant
        if tenant is None:
            return f"handled:{action.target}"
        return "executed"


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


def test_target_router_forwards_authenticated_tenant():
    from app.identity.models import AuthenticatedPrincipal, UserRole
    from app.identity.tenant import TenantContext

    operation = RecordingOperation()
    router = TargetRoutedOperation({"appointment": operation})

    principal = AuthenticatedPrincipal(
        user_id="user-001",
        business_id="business-001",
        role=UserRole.OWNER,
        session_id="session-001",
    )
    tenant = TenantContext(
        business_id="business-001",
        principal=principal,
    )

    action = AssistantAction(
        business_id="business-001",
        action_type="none",
        target="appointment",
        instruction="Test tenant propagation.",
        reversible=False,
    )

    result = router.execute(action, tenant=tenant)

    assert result == "executed"
    assert operation.last_tenant is tenant
