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

    result = executor.execute(make_action("create"))

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
