from __future__ import annotations

from app.assistant.capability_router import CapabilityRouter
from app.assistant.execution import (
    CapabilityExecutionRequest,
    CapabilityExecutionResult,
)
from app.trust.capability_policy import CapabilityPolicy
from app.safety.enforcement import SafetyEnforcement


class CapabilityExecutor:
    """
    Canonical trust boundary for capability execution.

    The executor validates authorization and safety before allowing
    a request to reach the capability router.

    It does not:
    - classify user requests,
    - interpret natural language,
    - determine commercial pricing,
    - select arbitrary Python functions,
    - execute shell/database code,
    - bypass capability registration.
    """

    def __init__(
        self,
        policy: CapabilityPolicy,
        router: CapabilityRouter,
        safety_enforcement: SafetyEnforcement,
    ) -> None:
        if not isinstance(policy, CapabilityPolicy):
            raise TypeError("policy must be a CapabilityPolicy.")

        if not isinstance(router, CapabilityRouter):
            raise TypeError("router must be a CapabilityRouter.")

        if not isinstance(safety_enforcement, SafetyEnforcement):
            raise TypeError(
                "safety_enforcement must be a SafetyEnforcement."
            )

        self._policy = policy
        self._router = router
        self._safety_enforcement = safety_enforcement

    def execute(
        self,
        request: CapabilityExecutionRequest,
    ) -> CapabilityExecutionResult:
        """
        Authorize, safety-check, and route one concrete capability operation.

        Denied requests never reach the capability router.
        """

        if not isinstance(request, CapabilityExecutionRequest):
            raise TypeError(
                "request must be a CapabilityExecutionRequest."
            )

        if request.business_id != self._policy.business_id:
            raise PermissionError(
                "Capability execution is not permitted for this business."
            )

        if not self._policy.allows_capability(request.capability):
            raise PermissionError(
                f"Capability '{request.capability.value}' is not permitted."
            )

        self._safety_enforcement.require_execution_allowed(
            request.business_id
        )
        self._safety_enforcement.require_capability_allowed(
            request.capability.value
        )

        if request.channel is not None:
            self._safety_enforcement.require_channel_allowed(
                request.channel
            )

        if request.integration is not None:
            self._safety_enforcement.require_integration_allowed(
                request.integration
            )

        result = self._router.route(request)

        if not isinstance(result, CapabilityExecutionResult):
            raise TypeError(
                "capability router must return a "
                "CapabilityExecutionResult."
            )

        if result.capability is not request.capability:
            raise ValueError(
                "Capability result does not match the request capability."
            )

        if result.operation != request.operation:
            raise ValueError(
                "Capability result does not match the request operation."
            )

        if result.business_id != request.business_id:
            raise ValueError(
                "Capability result does not belong to the request business."
            )

        return result
