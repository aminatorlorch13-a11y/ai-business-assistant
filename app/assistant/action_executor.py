from app.assistant.action import AssistantAction
from app.services.business_operation import BusinessOperation
from app.trust.action_policy import ActionPolicy
from app.trust.action_safety import ActionSafetyPolicy


class ActionExecutor:
    """Authorizes, safety-checks, and executes assistant actions."""

    def __init__(
        self,
        policy: ActionPolicy,
        operation: BusinessOperation,
        safety_policy: ActionSafetyPolicy | None = None,
    ) -> None:
        self._policy = policy
        self._operation = operation
        self._safety_policy = safety_policy or ActionSafetyPolicy()

    def execute(
        self,
        action: AssistantAction,
        confirmed: bool = False,
    ) -> str:
        """Execute an action when authorization and confirmation requirements pass."""

        if not self._policy.allows(action):
            raise PermissionError(
                f"Action '{action.action_type}' is not permitted."
            )

        if self._safety_policy.requires_confirmation(action) and not confirmed:
            raise PermissionError(
                f"Action '{action.action_type}' requires confirmation."
            )

        return self._operation.execute(action)
