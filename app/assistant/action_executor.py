from app.assistant.action import AssistantAction
from app.services.business_operation import BusinessOperation
from app.trust.action_policy import ActionPolicy
from app.trust.action_safety import ActionSafetyPolicy


class ActionExecutor:
    """Authorizes, safety-checks, and executes validated assistant actions."""

    def __init__(
        self,
        policy: ActionPolicy,
        operation: BusinessOperation,
        safety_policy: ActionSafetyPolicy | None = None,
    ) -> None:
        if not isinstance(policy, ActionPolicy):
            raise TypeError("policy must be an ActionPolicy.")

        if not isinstance(operation, BusinessOperation):
            raise TypeError("operation must be a BusinessOperation.")

        self._policy = policy
        self._operation = operation
        self._safety_policy = safety_policy or ActionSafetyPolicy()

    def execute(
        self,
        action: AssistantAction,
        confirmed: bool = False,
    ) -> str:
        """Execute an action only after every trust boundary passes."""

        if not isinstance(action, AssistantAction):
            raise TypeError("action must be an AssistantAction.")

        if not isinstance(confirmed, bool):
            raise TypeError("confirmed must be a boolean.")

        if not self._policy.allows(action):
            raise PermissionError(
                f"Action '{action.action_type}' is not permitted."
            )

        if (
            self._safety_policy.requires_confirmation(action)
            and not confirmed
        ):
            raise PermissionError(
                f"Action '{action.action_type}' requires confirmation."
            )

        result = self._operation.execute(action)

        if not isinstance(result, str):
            raise TypeError(
                "Business operation must return a string result."
            )

        if not result.strip():
            raise ValueError(
                "Business operation returned an empty result."
            )

        return result
