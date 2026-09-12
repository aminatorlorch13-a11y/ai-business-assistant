from app.assistant.action import AssistantAction
from app.assistant.execution_errors import (
    ActionConfirmationRequiredError,
    ActionOperationError,
    ActionPolicyDeniedError,
)
from app.services.business_operation import BusinessOperation
from app.trust.action_policy import ActionPolicy
from app.trust.action_safety import ActionSafetyPolicy
from app.identity.tenant import TenantContext


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
        tenant: TenantContext | None = None,
    ) -> str:
        """Execute an action only after every trust boundary passes."""

        if not isinstance(action, AssistantAction):
            raise TypeError("action must be an AssistantAction.")
        if not isinstance(confirmed, bool):
            raise TypeError("confirmed must be a boolean.")
        if tenant is not None and not isinstance(tenant, TenantContext):
            raise TypeError("tenant must be a TenantContext or None.")

        if tenant is not None and action.business_id != tenant.business_id:
            raise PermissionError(
                "Action business does not match the execution tenant."
            )

        if not self._policy.allows(action):
            raise ActionPolicyDeniedError(
                f"Action '{action.action_type}' is not permitted."
            )

        if (
            self._safety_policy.requires_confirmation(action)
            and not confirmed
        ):
            raise ActionConfirmationRequiredError(
                f"Action '{action.action_type}' requires confirmation."
            )

        try:
            if tenant is None:
                result = self._operation.execute(action)
            else:
                result = self._operation.execute(action, tenant=tenant)
        except ActionPolicyDeniedError:
            raise
        except ActionConfirmationRequiredError:
            raise
        except Exception as exc:
            raise ActionOperationError(
                f"Business operation failed for action "
                f"'{action.action_type}'."
            ) from exc

        if not isinstance(result, str):
            raise TypeError(
                "Business operation must return a string result."
            )

        if not result.strip():
            raise ValueError(
                "Business operation returned an empty result."
            )

        return result
