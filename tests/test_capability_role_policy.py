import pytest

from app.assistant.capability import Capability
from app.assistant.execution import CapabilityExecutionRequest
from app.identity.models import AuthenticatedPrincipal, UserRole
from app.identity.tenant import TenantContext
from app.trust.capability_role_policy import (
    CapabilityRoleOperationPolicy,
)


def make_policy() -> CapabilityRoleOperationPolicy:
    return CapabilityRoleOperationPolicy(
        allowed_operations_by_role={
            UserRole.OWNER: {
                Capability.CALCULATOR: frozenset({"calculate"}),
                Capability.CALENDAR: frozenset({
                    "create_event",
                    "update_event",
                    "delete_event",
                }),
            },
            UserRole.ADMIN: {
                Capability.CALCULATOR: frozenset({"calculate"}),
                Capability.CALENDAR: frozenset({
                    "create_event",
                    "update_event",
                    "delete_event",
                }),
            },
            UserRole.MEMBER: {
                Capability.CALCULATOR: frozenset({"calculate"}),
            },
        }
    )


def make_tenant(
    role: UserRole = UserRole.OWNER,
    business_id: str = "business-001",
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


def make_request(
    capability: Capability = Capability.CALCULATOR,
    operation: str = "calculate",
    business_id: str = "business-001",
) -> CapabilityExecutionRequest:
    return CapabilityExecutionRequest(
        capability=capability,
        operation=operation,
        business_id=business_id,
        arguments={"expression": "2 + 2"},
        reason="Perform the requested calculation.",
    )


def test_owner_is_authorized_for_registered_calculator_operation():
    assert make_policy().allows(
        make_tenant(UserRole.OWNER),
        make_request(),
    ) is True


def test_admin_is_authorized_for_registered_calculator_operation():
    assert make_policy().allows(
        make_tenant(UserRole.ADMIN),
        make_request(),
    ) is True


def test_member_is_authorized_for_registered_safe_calculator_operation():
    assert make_policy().allows(
        make_tenant(UserRole.MEMBER),
        make_request(),
    ) is True


def test_member_is_denied_calendar_mutation():
    assert make_policy().allows(
        make_tenant(UserRole.MEMBER),
        make_request(
            capability=Capability.CALENDAR,
            operation="create_event",
        ),
    ) is False


@pytest.mark.parametrize(
    "operation",
    [
        "create_event",
        "update_event",
        "delete_event",
    ],
)
def test_admin_is_authorized_for_registered_calendar_operations(operation):
    assert make_policy().allows(
        make_tenant(UserRole.ADMIN),
        make_request(
            capability=Capability.CALENDAR,
            operation=operation,
        ),
    ) is True


def test_unknown_operation_is_denied():
    assert make_policy().allows(
        make_tenant(UserRole.OWNER),
        make_request(
            capability=Capability.CALENDAR,
            operation="fly_to_moon",
        ),
    ) is False


def test_unknown_capability_is_denied():
    assert make_policy().allows(
        make_tenant(UserRole.OWNER),
        make_request(
            capability=Capability.MEMORY,
            operation="remember",
        ),
    ) is False


def test_cross_business_request_is_denied():
    assert make_policy().allows(
        make_tenant(
            UserRole.OWNER,
            business_id="business-001",
        ),
        make_request(
            business_id="business-002",
        ),
    ) is False


def test_require_raises_for_unauthorized_operation():
    with pytest.raises(PermissionError):
        make_policy().require(
            make_tenant(UserRole.MEMBER),
            make_request(
                capability=Capability.CALENDAR,
                operation="create_event",
            ),
        )


def test_require_allows_authorized_operation():
    make_policy().require(
        make_tenant(UserRole.OWNER),
        make_request(),
    )


def test_policy_rejects_invalid_role_key():
    with pytest.raises(TypeError):
        CapabilityRoleOperationPolicy(
            allowed_operations_by_role={
                "owner": {
                    Capability.CALCULATOR: frozenset({"calculate"}),
                },
            }
        )


def test_policy_rejects_invalid_capability_key():
    with pytest.raises(TypeError):
        CapabilityRoleOperationPolicy(
            allowed_operations_by_role={
                UserRole.OWNER: {
                    "calculator": frozenset({"calculate"}),
                },
            }
        )


def test_policy_rejects_non_frozenset_operations():
    with pytest.raises(TypeError):
        CapabilityRoleOperationPolicy(
            allowed_operations_by_role={
                UserRole.OWNER: {
                    Capability.CALCULATOR: {"calculate"},
                },
            }
        )


def test_policy_rejects_empty_operation():
    with pytest.raises(ValueError):
        CapabilityRoleOperationPolicy(
            allowed_operations_by_role={
                UserRole.OWNER: {
                    Capability.CALCULATOR: frozenset({"   "}),
                },
            }
        )


def test_policy_does_not_accept_ai_control_fields():
    request = CapabilityExecutionRequest(
        capability=Capability.CALCULATOR,
        operation="calculate",
        business_id="business-001",
        arguments={
            "reversible": False,
            "handler": "malicious_handler",
            "function": "__import__('os').system",
        },
        reason="Calculate the requested expression.",
    )

    assert make_policy().allows(
        make_tenant(UserRole.OWNER),
        request,
    ) is True


def test_policy_uses_authenticated_tenant_role_not_request_data():
    request = make_request(
        capability=Capability.CALENDAR,
        operation="delete_event",
    )

    tenant = make_tenant(UserRole.MEMBER)

    assert make_policy().allows(tenant, request) is False


def test_policy_rejects_wrong_tenant_type():
    with pytest.raises(TypeError):
        make_policy().allows(
            object(),
            make_request(),
        )


def test_policy_rejects_wrong_request_type():
    with pytest.raises(TypeError):
        make_policy().allows(
            make_tenant(),
            object(),
        )


def test_policy_does_not_authorize_platform_principal_as_tenant():
    from app.identity.models import SessionScope

    with pytest.raises(ValueError):
        TenantContext(
            business_id="business-001",
            principal=AuthenticatedPrincipal(
                user_id="founder-001",
                business_id=None,
                role=None,
                session_id="platform-session",
                scope=SessionScope.PLATFORM,
            ),
        )


def test_policy_is_immutable_at_top_level():
    policy = make_policy()

    with pytest.raises(Exception):
        policy.allowed_operations_by_role = {}


def test_policy_normalizes_operation_names():
    policy = CapabilityRoleOperationPolicy(
        allowed_operations_by_role={
            UserRole.OWNER: {
                Capability.CALCULATOR: frozenset({" calculate "}),
            },
        }
    )

    assert policy.allows(
        make_tenant(UserRole.OWNER),
        make_request(),
    ) is True
