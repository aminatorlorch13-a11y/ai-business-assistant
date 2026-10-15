from __future__ import annotations

from app.assistant.capability_router import CapabilityRouter
from app.assistant.execution import (
    CapabilityExecutionRequest,
    CapabilityExecutionResult,
)
from app.identity.tenant import TenantContext
from app.safety.enforcement import SafetyEnforcement
from app.trust.capability_policy import CapabilityPolicy
from app.trust.capability_role_policy import CapabilityRoleOperationPolicy


class CapabilityExecutor:
    """
    Canonical trust boundary for capability execution.

    Execution requires all independent trust boundaries to pass:

    1. authenticated tenant role authorization,
    2. business capability entitlement,
    3. emergency/channel/integration safety,
    4. exact registered capability operation routing.

    It does not:
    - classify user requests,
    - interpret natural language,
    - inspect untrusted AI control fields,
    - determine commercial pricing,
    - select arbitrary Python functions,
    - execute shell/database code,
    - bypass capability registration.
    """

    def __init__(
        self,
        policy: CapabilityPolicy,
        role_policy: CapabilityRoleOperationPolicy,
        router: CapabilityRouter,
        safety_enforcement: SafetyEnforcement,
    ) -> None:
        if not isinstance(policy, CapabilityPolicy):
            raise TypeError("policy must be a CapabilityPolicy.")

        if not isinstance(
            role_policy,
            CapabilityRoleOperationPolicy,
        ):
            raise TypeError(
                "role_policy must be a CapabilityRoleOperationPolicy."
            )

        if not isinstance(router, CapabilityRouter):
            raise TypeError("router must be a CapabilityRouter.")

        if not isinstance(safety_enforcement, SafetyEnforcement):
            raise TypeError(
                "safety_enforcement must be a SafetyEnforcement."
            )

        self._policy = policy
        self._role_policy = role_policy
        self._router = router
        self._safety_enforcement = safety_enforcement

    def authorize(
        self,
        request: CapabilityExecutionRequest,
        *,
        tenant: TenantContext,
    ) -> None:
        """Check execution authority and safety without routing an operation."""
        if not isinstance(
            request,
            CapabilityExecutionRequest,
        ):
            raise TypeError(
                "request must be a CapabilityExecutionRequest."
            )

        if not isinstance(tenant, TenantContext):
            raise TypeError(
                "tenant must be a TenantContext."
            )

        if request.business_id != tenant.business_id:
            raise PermissionError(
                "Capability execution is not permitted for this business."
            )

        self._role_policy.require(
            tenant,
            request,
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

        return None

    def execute(
        self,
        request: CapabilityExecutionRequest,
        *,
        tenant: TenantContext,
    ) -> CapabilityExecutionResult:
        """
        Authorize, safety-check, and route one concrete capability operation.

        Denied requests never reach the capability router.
        """
        self.authorize(request, tenant=tenant)

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
