from app.assistant.capability import CapabilityRequest, CapabilityResult
from app.assistant.capability_router import CapabilityRouter
from app.trust.capability_policy import CapabilityPolicy


class CapabilityExecutor:
    """
    Enforces capability authorization before routing execution.

    This is the trust boundary between an authorized capability request
    and the capability router.

    The executor does not classify requests, perform capabilities,
    determine pricing, or grant permissions.
    """

    def __init__(
        self,
        policy: CapabilityPolicy,
        router: CapabilityRouter,
    ) -> None:
        if not isinstance(policy, CapabilityPolicy):
            raise TypeError(
                "policy must be a CapabilityPolicy."
            )

        if not isinstance(router, CapabilityRouter):
            raise TypeError(
                "router must be a CapabilityRouter."
            )

        self._policy = policy
        self._router = router

    def execute(
        self,
        request: CapabilityRequest,
    ) -> CapabilityResult:
        """
        Authorize and route a capability request.

        Authorization is checked before the router is allowed to execute
        the request. Denied requests never reach a capability handler.
        """
        if not isinstance(request, CapabilityRequest):
            raise TypeError(
                "request must be a CapabilityRequest."
            )

        if not self._policy.allows(request):
            raise PermissionError(
                f"Capability '{request.capability.value}' "
                "is not permitted."
            )

        result = self._router.route(request)

        if not isinstance(result, CapabilityResult):
            raise TypeError(
                "capability router must return a CapabilityResult."
            )

        return result
