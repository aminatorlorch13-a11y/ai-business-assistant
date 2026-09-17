from __future__ import annotations

from app.assistant.action import AssistantAction
from app.assistant.execution_errors import ActionConfirmationRequiredError
from app.identity.tenant import TenantContext
from app.platform.events import PlatformEventOutcome
from app.safety.enforcement import SafetyExecutionDenied, SafetyEnforcement
from app.services.business_operation import BusinessOperation
from app.telemetry.execution import ExecutionTelemetry
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
        telemetry: ExecutionTelemetry | None = None,
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
        self._telemetry = telemetry

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
            raise ValueError(
                "channel must be a non-empty string when provided."
            )
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

        normalized_channel = (
            channel.strip() if channel is not None else None
        )
        normalized_integration = (
            integration.strip() if integration is not None else None
        )

        try:
            self._safety_enforcement.require_execution_allowed(
                action.business_id
            )
            self._safety_enforcement.require_capability_allowed(
                action.action_type
            )

            if normalized_channel is not None:
                self._safety_enforcement.require_channel_allowed(
                    normalized_channel
                )

            if normalized_integration is not None:
                self._safety_enforcement.require_integration_allowed(
                    normalized_integration
                )

            if not self._policy.allows(action):
                self._record_telemetry(
                    action=action,
                    tenant=tenant,
                    outcome=PlatformEventOutcome.DENIED,
                    channel=normalized_channel,
                    integration=normalized_integration,
                    reason="action_policy_denied",
                )
                raise ActionPolicyDeniedError(
                    f"Action type {action.action_type!r} is not permitted."
                )

            if (
                self._safety_policy.requires_confirmation(action)
                and not confirmed
            ):
                self._record_telemetry(
                    action=action,
                    tenant=tenant,
                    outcome=PlatformEventOutcome.DENIED,
                    channel=normalized_channel,
                    integration=normalized_integration,
                    reason="confirmation_required",
                )
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
                self._record_telemetry(
                    action=action,
                    tenant=tenant,
                    outcome=PlatformEventOutcome.FAILURE,
                    channel=normalized_channel,
                    integration=normalized_integration,
                    reason="operation_failed",
                )
                raise ActionOperationError(
                    "The business operation failed."
                ) from exc

            if not isinstance(result, str):
                self._record_telemetry(
                    action=action,
                    tenant=tenant,
                    outcome=PlatformEventOutcome.FAILURE,
                    channel=normalized_channel,
                    integration=normalized_integration,
                    reason="invalid_operation_result",
                )
                raise TypeError(
                    "Business operation result must be a string."
                )

            if not result.strip():
                self._record_telemetry(
                    action=action,
                    tenant=tenant,
                    outcome=PlatformEventOutcome.FAILURE,
                    channel=normalized_channel,
                    integration=normalized_integration,
                    reason="empty_operation_result",
                )
                raise ValueError(
                    "Business operation returned an empty result."
                )

            self._record_telemetry(
                action=action,
                tenant=tenant,
                outcome=PlatformEventOutcome.SUCCESS,
                channel=normalized_channel,
                integration=normalized_integration,
            )
            return result

        except SafetyExecutionDenied:
            self._record_telemetry(
                action=action,
                tenant=tenant,
                outcome=PlatformEventOutcome.DENIED,
                channel=normalized_channel,
                integration=normalized_integration,
                reason="safety_denied",
            )
            raise

    def _record_telemetry(
        self,
        *,
        action: AssistantAction,
        tenant: TenantContext | None,
        outcome: PlatformEventOutcome,
        channel: str | None,
        integration: str | None,
        reason: str | None = None,
    ) -> None:
        if self._telemetry is None:
            return

        try:
            self._telemetry.record(
                business_id=action.business_id,
                user_id=(
                    tenant.principal.user_id
                    if tenant is not None
                    else None
                ),
                action_type=action.action_type,
                outcome=outcome,
                channel=channel,
                integration=integration,
                reason=reason,
            )
        except Exception:
            # Telemetry is observational. It must never change the
            # authoritative execution result or exception semantics.
            return
