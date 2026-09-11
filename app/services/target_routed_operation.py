from collections.abc import Mapping

from app.assistant.action import AssistantAction
from app.services.business_operation import BusinessOperation


class TargetRoutedOperation(BusinessOperation):
    """
    Dispatches an action to the correct BusinessOperation by target.

    ActionExecutor is constructed with exactly one operation. This
    router lets that single operation represent many real handlers
    without changing ActionExecutor's contract.
    """

    def __init__(
        self,
        operations_by_target: Mapping[str, BusinessOperation],
    ) -> None:
        if not isinstance(operations_by_target, Mapping):
            raise TypeError(
                "operations_by_target must be a mapping."
            )

        for target, operation in operations_by_target.items():
            if not isinstance(target, str) or not target.strip():
                raise ValueError(
                    "operations_by_target keys must be "
                    "non-empty strings."
                )

            if not isinstance(operation, BusinessOperation):
                raise TypeError(
                    "operations_by_target values must be "
                    "BusinessOperation instances."
                )

        if not operations_by_target:
            raise ValueError(
                "operations_by_target must not be empty."
            )

        self._operations_by_target = dict(operations_by_target)

    def execute(self, action: AssistantAction) -> str:
        """Route the action to its registered handler and execute it."""

        operation = self._operations_by_target.get(action.target)

        if operation is None:
            raise ValueError(
                f"No operation registered for target: {action.target!r}."
            )

        return operation.execute(action)
