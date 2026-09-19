import pytest

from app.assistant.capability import Capability
from app.assistant.capability_router import CapabilityRouter
from app.assistant.execution import (
    CapabilityExecutionRequest,
    CapabilityExecutionResult,
)
from app.safety.enforcement import SafetyEnforcement
from app.trust.capability_executor import CapabilityExecutor
from app.trust.capability_policy import CapabilityPolicy
from app.trust.capability_role_policy import CapabilityRoleOperationPolicy
from app.identity.models import AuthenticatedPrincipal, UserRole
from app.identity.tenant import TenantContext
from tests.test_safety_helpers import AllowAllTestSafetyEnforcement


BUSINESS_ID = "business-001"


def make_request(
    capability: Capability = Capability.CONVERSATION,
    business_id: str = BUSINESS_ID,
    operation: str = "respond",
    arguments: dict | None = None,
    channel: str | None = None,
    integration: str | None = None,
) -> CapabilityExecutionRequest:
    return CapabilityExecutionRequest(
        capability=capability,
        operation=operation,
        business_id=business_id,
        arguments=arguments or {},
        reason="Handle the owner's request.",
        channel=channel,
        integration=integration,
    )


def make_policy(
    allowed_capabilities: frozenset[Capability] | None = None,
) -> CapabilityPolicy:
    if allowed_capabilities is None:
        allowed_capabilities = frozenset({Capability.CONVERSATION})

    return CapabilityPolicy(
        business_id=BUSINESS_ID,
        allowed_capabilities=allowed_capabilities,
    )


def make_role_policy() -> CapabilityRoleOperationPolicy:
    return CapabilityRoleOperationPolicy(
        allowed_operations_by_role={
            UserRole.OWNER: {
                Capability.CONVERSATION: frozenset({"respond"}),
                Capability.RESEARCH: frozenset({"respond"}),
            },
        }
    )


def make_tenant(
    role: UserRole = UserRole.OWNER,
    business_id: str = BUSINESS_ID,
) -> TenantContext:
    principal = AuthenticatedPrincipal(
        user_id="user-001",
        business_id=business_id,
        role=role,
        session_id="session-001",
    )
    return TenantContext(
        business_id=business_id,
        principal=principal,
    )


def make_router(
    calls: list | None = None,
    result_capability: Capability | None = None,
    result_operation: str | None = None,
    result_business_id: str | None = None,
) -> CapabilityRouter:
    if calls is None:
        calls = []

    def handler(request):
        calls.append(request)

        return CapabilityExecutionResult(
            success=True,
            capability=(
                result_capability
                if result_capability is not None
                else request.capability
            ),
            operation=(
                result_operation
                if result_operation is not None
                else request.operation
            ),
            business_id=(
                result_business_id
                if result_business_id is not None
                else request.business_id
            ),
            data={"status": "completed"},
            verification="test verification",
        )

    return CapabilityRouter(
        {
            capability: {
                "respond": handler,
            }
            for capability in Capability
        }
    )


def make_executor(
    calls: list | None = None,
    allowed_capabilities: frozenset[Capability] | None = None,
    safety_enforcement: SafetyEnforcement | None = None,
    result_capability: Capability | None = None,
    result_operation: str | None = None,
    result_business_id: str | None = None,
) -> CapabilityExecutor:
    return CapabilityExecutor(
        policy=make_policy(allowed_capabilities),
        role_policy=make_role_policy(),
        router=make_router(
            calls=calls,
            result_capability=result_capability,
            result_operation=result_operation,
            result_business_id=result_business_id,
        ),
        safety_enforcement=(
            safety_enforcement
            if safety_enforcement is not None
            else AllowAllTestSafetyEnforcement()
        ),
    )


def test_executor_authorizes_before_routing():
    calls = []

    executor = make_executor(
        calls=calls,
        allowed_capabilities=frozenset({Capability.CONVERSATION}),
    )

    request = make_request()
    result = executor.execute(request, tenant=make_tenant())

    assert isinstance(result, CapabilityExecutionResult)
    assert result.success is True
    assert result.capability is Capability.CONVERSATION
    assert result.operation == "respond"
    assert result.business_id == BUSINESS_ID
    assert calls == [request]


def test_executor_denies_unauthorized_capability():
    calls = []

    executor = make_executor(
        calls=calls,
        allowed_capabilities=frozenset({Capability.CONVERSATION}),
    )

    with pytest.raises(PermissionError, match="not permitted"):
        executor.execute(make_request(Capability.RESEARCH), tenant=make_tenant())

    assert calls == []


def test_denied_capability_never_reaches_handler():
    calls = []

    executor = make_executor(
        calls=calls,
        allowed_capabilities=frozenset(),
    )

    with pytest.raises(PermissionError):
        executor.execute(make_request(), tenant=make_tenant())

    assert calls == []


def test_cross_business_request_is_denied_before_routing():
    calls = []

    executor = make_executor(
        calls=calls,
        allowed_capabilities=frozenset({Capability.CONVERSATION}),
    )

    with pytest.raises(PermissionError):
        executor.execute(
            make_request(
                business_id="business-999",
            ),
            tenant=make_tenant(),
        )

    assert calls == []


@pytest.mark.parametrize(
    "request_value",
    [None, "request", object()],
)
def test_executor_rejects_invalid_request(request_value):
    executor = make_executor()

    with pytest.raises(
        TypeError,
        match="CapabilityExecutionRequest",
    ):
        executor.execute(request_value, tenant=make_tenant())


@pytest.mark.parametrize(
    "policy_value",
    [None, object()],
)
def test_executor_rejects_invalid_policy(policy_value):
    with pytest.raises(
        TypeError,
        match="CapabilityPolicy",
    ):
        CapabilityExecutor(
            policy=policy_value,
            role_policy=make_role_policy(),
            router=make_router(),
            safety_enforcement=AllowAllTestSafetyEnforcement(),
        )


@pytest.mark.parametrize(
    "router_value",
    [None, object()],
)
def test_executor_rejects_invalid_router(router_value):
    with pytest.raises(
        TypeError,
        match="CapabilityRouter",
    ):
        CapabilityExecutor(
            policy=make_policy(),
            role_policy=make_role_policy(),
            router=router_value,
            safety_enforcement=AllowAllTestSafetyEnforcement(),
        )


@pytest.mark.parametrize(
    "safety_value",
    [None, object()],
)
def test_executor_rejects_invalid_safety_enforcement(safety_value):
    with pytest.raises(
        TypeError,
        match="SafetyEnforcement",
    ):
        CapabilityExecutor(
            policy=make_policy(),
            role_policy=make_role_policy(),
            router=make_router(),
            safety_enforcement=safety_value,
        )


def test_executor_rejects_result_with_wrong_capability():
    executor = make_executor(
        allowed_capabilities=frozenset({Capability.CONVERSATION}),
        result_capability=Capability.RESEARCH,
    )

    with pytest.raises(
        ValueError,
        match="result does not match the request capability",
    ):
        executor.execute(make_request(), tenant=make_tenant())


def test_executor_rejects_result_with_wrong_operation():
    executor = make_executor(
        allowed_capabilities=frozenset({Capability.CONVERSATION}),
        result_operation="different-operation",
    )

    with pytest.raises(
        ValueError,
        match="result does not match the request operation",
    ):
        executor.execute(make_request(), tenant=make_tenant())


def test_executor_rejects_result_from_wrong_business():
    executor = make_executor(
        allowed_capabilities=frozenset({Capability.CONVERSATION}),
        result_business_id="business-999",
    )

    with pytest.raises(
        ValueError,
        match="result does not belong to the request business",
    ):
        executor.execute(make_request(), tenant=make_tenant())


def test_executor_passes_channel_to_safety_boundary():
    class RecordingSafety(AllowAllTestSafetyEnforcement):
        def __init__(self):
            self.channels = []

        def require_channel_allowed(self, channel):
            self.channels.append(channel)

    safety = RecordingSafety()
    executor = make_executor(
        safety_enforcement=safety,
    )

    executor.execute(
        make_request(channel="web"),
        tenant=make_tenant(),
    )

    assert safety.channels == ["web"]


def test_executor_passes_integration_to_safety_boundary():
    class RecordingSafety(AllowAllTestSafetyEnforcement):
        def __init__(self):
            self.integrations = []

        def require_integration_allowed(self, integration):
            self.integrations.append(integration)

    safety = RecordingSafety()
    executor = make_executor(
        safety_enforcement=safety,
    )

    executor.execute(
        make_request(
            integration="calendar",
        ),
        tenant=make_tenant(),
    )

    assert safety.integrations == ["calendar"]


def test_executor_checks_execution_safety_before_routing():
    calls = []

    class DenyingSafety(AllowAllTestSafetyEnforcement):
        def require_execution_allowed(self, business_id):
            raise PermissionError("execution halted")

    executor = make_executor(
        calls=calls,
        safety_enforcement=DenyingSafety(),
    )

    with pytest.raises(PermissionError, match="execution halted"):
        executor.execute(make_request(), tenant=make_tenant())

    assert calls == []


def test_executor_checks_capability_safety_before_routing():
    calls = []

    class DenyingSafety(AllowAllTestSafetyEnforcement):
        def require_capability_allowed(self, capability):
            raise PermissionError("capability halted")

    executor = make_executor(
        calls=calls,
        safety_enforcement=DenyingSafety(),
    )

    with pytest.raises(PermissionError, match="capability halted"):
        executor.execute(make_request(), tenant=make_tenant())

    assert calls == []


def test_executor_checks_channel_safety_before_routing():
    calls = []

    class DenyingSafety(AllowAllTestSafetyEnforcement):
        def require_channel_allowed(self, channel):
            raise PermissionError("channel halted")

    executor = make_executor(
        calls=calls,
        safety_enforcement=DenyingSafety(),
    )

    with pytest.raises(PermissionError, match="channel halted"):
        executor.execute(
        make_request(channel="web"),
        tenant=make_tenant(),
    )

    assert calls == []


def test_executor_checks_integration_safety_before_routing():
    calls = []

    class DenyingSafety(AllowAllTestSafetyEnforcement):
        def require_integration_allowed(self, integration):
            raise PermissionError("integration halted")

    executor = make_executor(
        calls=calls,
        safety_enforcement=DenyingSafety(),
    )

    with pytest.raises(PermissionError, match="integration halted"):
        executor.execute(
            make_request(integration="calendar"),
            tenant=make_tenant(),
        )

    assert calls == []
