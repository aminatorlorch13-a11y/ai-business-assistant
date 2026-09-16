from __future__ import annotations

from app.assistant.action import AssistantAction
from app.assistant.execution_errors import (
    ActionConfirmationRequiredError,
)
from app.identity.tenant import TenantContext
from app.safety.enforcement import SafetyEnforcement
from app.services.business_operation import BusinessOperation
from app.trust.action_policy import ActionPolicy
from app.trust.action_safety import ActionSafetyPolicy


class ActionPolicyDeniedError(PermissionError):
    """Raised when the action policy rejects an action."""


class ActionOperationError(RuntimeError):
    """Raised when the underlying business operation fails."""


class ActionExecutor:
    """Authorizes, safety-checks, and executes validated assistant actions."""

    def __init__(
        self,
        policy: ActionPolicy,
        operation: BusinessOperation,
        safety_enforcement: SafetyEnforcement,
        safety_policy: ActionSafetyPolicy | None = None,
    ) -> None:
        if not isinstance(policy, ActionPolicy):
            raise TypeError("policy must be an ActionPolicy.")

        if not isinstance(operation, BusinessOperation):
            raise TypeError("operation must be a BusinessOperation.")

        if not isinstance(safety_enforcement, SafetyEnforcement):
            raise TypeError(
                "safety_enforcement must be a SafetyEnforcement."
            )

        self._policy = policy
        self._operation = operation
        self._safety_enforcement = safety_enforcement
        self._safety_policy = safety_policy or ActionSafetyPolicy()

    def execute(
        self,
        action: AssistantAction,
        confirmed: bool = False,
        tenant: TenantContext | None = None,
        *,
        channel: str | None = None,
        integration: str | None = None,
    ) -> str:
        if not isinstance(action, AssistantAction):
            raise TypeError("action must be an AssistantAction.")

        if not isinstance(confirmed, bool):
            raise TypeError("confirmed must be a bool.")

        if tenant is not None and not isinstance(tenant, TenantContext):
            raise TypeError("tenant must be a TenantContext or None.")

        if channel is not None and (
            not isinstance(channel, str) or not channel.strip()
        ):
            raise ValueError("channel must be a non-empty string when provided.")

        if integration is not None and (
            not isinstance(integration, str) or not integration.strip()
        ):
            raise ValueError(
                "integration must be a non-empty string when provided."
            )

        if tenant is not None and action.business_id != tenant.business_id:
            raise PermissionError(
                "Action business does not match the execution tenant."
            )

        # Emergency safety is a hard execution boundary.
        # It runs before policy confirmation and before the underlying
        # business operation can execute.
        self._safety_enforcement.require_execution_allowed(
            action.business_id
        )

        # The action type is the capability being requested.
        self._safety_enforcement.require_capability_allowed(
            action.action_type
        )

        # Channel and integration are execution context, not properties
        # invented by the assistant. They must be supplied by the trusted
        # caller when known.
        if channel is not None:
            self._safety_enforcement.require_channel_allowed(channel.strip())

        if integration is not None:
            self._safety_enforcement.require_integration_allowed(
                integration.strip()
            )

        if not self._policy.allows(action):
            raise ActionPolicyDeniedError(
                f"Action type {action.action_type!r} is not permitted."
            )

        if (
            self._safety_policy.requires_confirmation(action)
            and not confirmed
        ):
            raise ActionConfirmationRequiredError(
                "This action requires explicit confirmation."
            )

        try:
            if tenant is None:
                result = self._operation.execute(action)
            else:
                result = self._operation.execute(
                    action,
                    tenant=tenant,
                )
        except ActionPolicyDeniedError:
            raise
        except ActionConfirmationRequiredError:
            raise
        except Exception as exc:
            raise ActionOperationError(
                "The business operation failed."
            ) from exc

        if not isinstance(result, str):
            raise TypeError("Business operation result must be a string.")

        if not result.strip():
            raise ValueError(
                "Business operation returned an empty result."
            )

        return result
