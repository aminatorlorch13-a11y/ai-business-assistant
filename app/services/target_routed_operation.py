from collections.abc import Mapping

from app.assistant.action import AssistantAction
from app.identity.tenant import TenantContext
from app.services.business_operation import BusinessOperation


class TargetRoutedOperation(BusinessOperation):
    """
    Dispatch an action to the correct BusinessOperation by target.

    ActionExecutor remains the single execution boundary. This router only
    selects the concrete operation and forwards the authenticated tenant.
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

    def execute(
        self,
        action: AssistantAction,
        tenant: TenantContext | None = None,
    ) -> str:
        """Route the action and preserve the execution tenant."""

        operation = self._operations_by_target.get(action.target)

        if operation is None:
            raise ValueError(
                f"No operation registered for target: "
                f"{action.target!r}."
            )

        if tenant is None:
            return operation.execute(action)

        return operation.execute(action, tenant=tenant)
