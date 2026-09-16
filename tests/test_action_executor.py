import pytest
from unittest.mock import Mock

from app.assistant.action import AssistantAction
from app.assistant.action_executor import ActionExecutor
from app.services.business_operation import BusinessOperation
from app.trust.action_policy import ActionPolicy
from tests.test_safety_helpers import AllowAllTestSafetyEnforcement


def make_safety_enforcement():
    return AllowAllTestSafetyEnforcement()


def make_action(action_type: str) -> AssistantAction:
    return AssistantAction(
        business_id="business-001",
        action_type=action_type,
        target="appointment",
        instruction="Perform the requested operation.",
    )


def test_executor_executes_permitted_action():
    operation = Mock(spec=BusinessOperation)
    operation.execute.return_value = "Operation completed."

    executor = ActionExecutor(
        policy=ActionPolicy(),
        operation=operation,
        safety_enforcement=make_safety_enforcement(),
    )

    result = executor.execute(make_action("create"), confirmed=True)

    assert result == "Operation completed."
    operation.execute.assert_called_once_with(make_action("create"))


def test_executor_allows_none_action():
    operation = Mock(spec=BusinessOperation)
    operation.execute.return_value = "Nothing required."

    executor = ActionExecutor(
        policy=ActionPolicy(),
        operation=operation,
        safety_enforcement=make_safety_enforcement(),
    )

    result = executor.execute(make_action("none"))

    assert result == "Nothing required."
    operation.execute.assert_called_once()


def test_executor_rejects_forbidden_action():
    operation = Mock(spec=BusinessOperation)

    executor = ActionExecutor(
        policy=ActionPolicy(),
        operation=operation,
        safety_enforcement=make_safety_enforcement(),
    )

    with pytest.raises(PermissionError):
        executor.execute(make_action("delete"))

    operation.execute.assert_not_called()


def test_executor_respects_disabled_create_permission():
    operation = Mock(spec=BusinessOperation)

    executor = ActionExecutor(
        policy=ActionPolicy(allow_create=False),
        operation=operation,
        safety_enforcement=make_safety_enforcement(),
    )

    with pytest.raises(PermissionError):
        executor.execute(make_action("create"))

    operation.execute.assert_not_called()


def test_executor_respects_disabled_update_permission():
    operation = Mock(spec=BusinessOperation)

    executor = ActionExecutor(
        policy=ActionPolicy(allow_update=False),
        operation=operation,
        safety_enforcement=make_safety_enforcement(),
    )

    with pytest.raises(PermissionError):
        executor.execute(make_action("update"))

    operation.execute.assert_not_called()


def test_executor_requires_confirmation_for_unsafe_action():
    operation = Mock(spec=BusinessOperation)
    safety_policy = Mock()
    safety_policy.requires_confirmation.return_value = True

    executor = ActionExecutor(
        policy=ActionPolicy(),
        operation=operation,
        safety_enforcement=make_safety_enforcement(),
        safety_policy=safety_policy,
    )

    with pytest.raises(PermissionError, match="confirmation"):
        executor.execute(make_action("create"))

    safety_policy.requires_confirmation.assert_called_once_with(
        make_action("create")
    )
    operation.execute.assert_not_called()


def test_executor_executes_action_when_confirmation_is_not_required():
    operation = Mock(spec=BusinessOperation)
    operation.execute.return_value = "Operation completed."

    safety_policy = Mock()
    safety_policy.requires_confirmation.return_value = False

    executor = ActionExecutor(
        policy=ActionPolicy(),
        operation=operation,
        safety_enforcement=make_safety_enforcement(),
        safety_policy=safety_policy,
    )

    result = executor.execute(make_action("create"), confirmed=True)

    assert result == "Operation completed."
    safety_policy.requires_confirmation.assert_called_once_with(
        make_action("create")
    )
    operation.execute.assert_called_once_with(
        make_action("create")
    )


def test_executor_rejects_non_action_input():
    operation = Mock(spec=BusinessOperation)
    executor = ActionExecutor(
        policy=ActionPolicy(),
        operation=operation,
        safety_enforcement=make_safety_enforcement(),
    )

    with pytest.raises(TypeError, match="AssistantAction"):
        executor.execute(object())


def test_executor_rejects_non_boolean_confirmation():
    operation = Mock(spec=BusinessOperation)
    executor = ActionExecutor(
        policy=ActionPolicy(),
        operation=operation,
        safety_enforcement=make_safety_enforcement(),
    )

    with pytest.raises(TypeError, match="confirmed must be a bool"):
        executor.execute(make_action("none"), confirmed="yes")


def test_executor_rejects_non_string_operation_result():
    operation = Mock(spec=BusinessOperation)
    operation.execute.return_value = 123

    executor = ActionExecutor(
        policy=ActionPolicy(),
        operation=operation,
        safety_enforcement=make_safety_enforcement(),
    )

    with pytest.raises(TypeError, match="Business operation result must be a string"):
        executor.execute(make_action("none"))


def test_executor_rejects_empty_operation_result():
    operation = Mock(spec=BusinessOperation)
    operation.execute.return_value = "   "

    executor = ActionExecutor(
        policy=ActionPolicy(),
        operation=operation,
        safety_enforcement=make_safety_enforcement(),
    )

    with pytest.raises(ValueError, match="empty result"):
        executor.execute(make_action("none"))


def test_executor_rejects_action_for_wrong_tenant():
    from app.identity.models import AuthenticatedPrincipal, UserRole
    from app.identity.tenant import TenantContext

    operation = Mock(spec=BusinessOperation)
    executor = ActionExecutor(
        policy=ActionPolicy(),
        operation=operation,
        safety_enforcement=make_safety_enforcement(),
    )

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

    action = make_action("none")
    action = AssistantAction(
        business_id="business-002",
        action_type=action.action_type,
        target=action.target,
        instruction=action.instruction,
        reversible=action.reversible,
    )

    with pytest.raises(PermissionError, match="execution tenant"):
        executor.execute(action, tenant=tenant)

    operation.execute.assert_not_called()


def test_executor_forwards_authenticated_tenant_to_operation():
    from app.identity.models import AuthenticatedPrincipal, UserRole
    from app.identity.tenant import TenantContext

    operation = Mock(spec=BusinessOperation)
    operation.execute.return_value = "executed"

    executor = ActionExecutor(
        policy=ActionPolicy(),
        operation=operation,
        safety_enforcement=make_safety_enforcement(),
    )

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

    action = make_action("none")

    result = executor.execute(action, tenant=tenant)

    assert result == "executed"
    operation.execute.assert_called_once_with(action, tenant=tenant)
