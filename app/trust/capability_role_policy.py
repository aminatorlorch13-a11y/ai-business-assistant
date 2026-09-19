from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from app.assistant.capability import Capability
from app.assistant.execution import CapabilityExecutionRequest
from app.identity.models import UserRole
from app.identity.tenant import TenantContext


@dataclass(frozen=True)
class CapabilityRoleOperationPolicy:
    """
    Trusted application-owned authorization policy for capability operations.

    This policy answers one question only:

        May the authenticated principal's role perform this exact
        capability + operation?

    It does not:
    - determine commercial entitlement,
    - inspect AI proposals,
    - perform safety enforcement,
    - determine confirmation requirements,
    - route operations,
    - execute capabilities.

    Business identity comes from TenantContext and must match the
    CapabilityExecutionRequest business identity.
    """

    allowed_operations_by_role: Mapping[
        UserRole,
        Mapping[Capability, frozenset[str]],
    ]

    def __post_init__(self) -> None:
        if not isinstance(self.allowed_operations_by_role, Mapping):
            raise TypeError(
                "allowed_operations_by_role must be a mapping."
            )

        normalized: dict[
            UserRole,
            dict[Capability, frozenset[str]],
        ] = {}

        for role, capabilities in self.allowed_operations_by_role.items():
            if not isinstance(role, UserRole):
                raise TypeError(
                    "Policy role keys must be UserRole values."
                )

            if not isinstance(capabilities, Mapping):
                raise TypeError(
                    "Policy capability mappings must be mappings."
                )

            normalized_capabilities: dict[
                Capability,
                frozenset[str],
            ] = {}

            for capability, operations in capabilities.items():
                if not isinstance(capability, Capability):
                    raise TypeError(
                        "Policy capability keys must be Capability values."
                    )

                if not isinstance(operations, frozenset):
                    raise TypeError(
                        "Policy operations must be frozensets."
                    )

                normalized_operations: set[str] = set()

                for operation in operations:
                    if not isinstance(operation, str):
                        raise TypeError(
                            "Policy operation names must be strings."
                        )

                    operation = operation.strip()

                    if not operation:
                        raise ValueError(
                            "Policy operation names must be non-empty."
                        )

                    normalized_operations.add(operation)

                normalized_capabilities[capability] = frozenset(
                    normalized_operations
                )

            normalized[role] = normalized_capabilities

        object.__setattr__(
            self,
            "allowed_operations_by_role",
            {
                role: dict(capabilities)
                for role, capabilities in normalized.items()
            },
        )

    def allows(
        self,
        tenant: TenantContext,
        request: CapabilityExecutionRequest,
    ) -> bool:
        """
        Return whether the authenticated tenant principal may execute
        the requested capability operation.

        Denial is the default for unknown roles, capabilities, operations,
        and business identity mismatches.
        """
        if not isinstance(tenant, TenantContext):
            raise TypeError("tenant must be a TenantContext.")

        if not isinstance(
            request,
            CapabilityExecutionRequest,
        ):
            raise TypeError(
                "request must be a CapabilityExecutionRequest."
            )

        if request.business_id != tenant.business_id:
            return False

        role = tenant.principal.role

        if not isinstance(role, UserRole):
            return False

        capabilities = self.allowed_operations_by_role.get(role)

        if capabilities is None:
            return False

        operations = capabilities.get(request.capability)

        if operations is None:
            return False

        return request.operation in operations

    def require(
        self,
        tenant: TenantContext,
        request: CapabilityExecutionRequest,
    ) -> None:
        """
        Require role authorization for a capability operation.
        """
        if not self.allows(tenant, request):
            raise PermissionError(
                "Authenticated principal is not authorized for "
                f"capability '{request.capability.value}' "
                f"operation '{request.operation}'."
            )
