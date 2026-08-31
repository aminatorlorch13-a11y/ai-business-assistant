from app.assistant.action import AssistantAction
from app.services.business_operation import BusinessOperation
from app.trust.action_policy import ActionPolicy


class ActionExecutor:
    """Authorizes and executes assistant actions."""

    def __init__(
        self,
        policy: ActionPolicy,
        operation: BusinessOperation,
    ) -> None:
        self._policy = policy
        self._operation = operation

    def execute(self, action: AssistantAction) -> str:
        """Execute an action when permitted by policy."""

        if not self._policy.allows(action):
            raise PermissionError(
                f"Action '{action.action_type}' is not permitted."
            )

        return self._operation.execute(action)
