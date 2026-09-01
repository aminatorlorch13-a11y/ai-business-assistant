import pytest
from unittest.mock import Mock

from app.assistant.action import AssistantAction
from app.assistant.action_executor import ActionExecutor
from app.services.business_operation import BusinessOperation
from app.trust.action_policy import ActionPolicy


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
    )

    result = executor.execute(make_action("none"))

    assert result == "Nothing required."
    operation.execute.assert_called_once()


def test_executor_rejects_forbidden_action():
    operation = Mock(spec=BusinessOperation)

    executor = ActionExecutor(
        policy=ActionPolicy(),
        operation=operation,
    )

    with pytest.raises(PermissionError):
        executor.execute(make_action("delete"))

    operation.execute.assert_not_called()


def test_executor_respects_disabled_create_permission():
    operation = Mock(spec=BusinessOperation)

    executor = ActionExecutor(
        policy=ActionPolicy(allow_create=False),
        operation=operation,
    )

    with pytest.raises(PermissionError):
        executor.execute(make_action("create"))

    operation.execute.assert_not_called()


def test_executor_respects_disabled_update_permission():
    operation = Mock(spec=BusinessOperation)

    executor = ActionExecutor(
        policy=ActionPolicy(allow_update=False),
        operation=operation,
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
    )

    with pytest.raises(TypeError, match="AssistantAction"):
        executor.execute(object())


def test_executor_rejects_non_boolean_confirmation():
    operation = Mock(spec=BusinessOperation)
    executor = ActionExecutor(
        policy=ActionPolicy(),
        operation=operation,
    )

    with pytest.raises(TypeError, match="boolean"):
        executor.execute(make_action("none"), confirmed="yes")


def test_executor_rejects_non_string_operation_result():
    operation = Mock(spec=BusinessOperation)
    operation.execute.return_value = 123

    executor = ActionExecutor(
        policy=ActionPolicy(),
        operation=operation,
    )

    with pytest.raises(TypeError, match="string result"):
        executor.execute(make_action("none"))


def test_executor_rejects_empty_operation_result():
    operation = Mock(spec=BusinessOperation)
    operation.execute.return_value = "   "

    executor = ActionExecutor(
        policy=ActionPolicy(),
        operation=operation,
    )

    with pytest.raises(ValueError, match="empty result"):
        executor.execute(make_action("none"))
