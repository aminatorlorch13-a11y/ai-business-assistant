from __future__ import annotations

from collections.abc import Mapping

from app.assistant.capability import Capability
from app.assistant.capability_registry import build_capability_router
from app.assistant.capability_router import CapabilityRouter
from app.commercial.entitlement_resolver import ExplicitEntitlementResolver
from app.identity.models import UserRole
from app.memory.scoped_service import ScopedMemoryService
from app.persistence.memory_repository import SQLiteMemoryRepository
from app.persistence.safety_repository import SQLiteSafetyRepository
from app.safety.enforcement import SafetyEnforcement
from app.trust.capability_executor import CapabilityExecutor
from app.trust.capability_operation_policy import CapabilityOperationPolicy
from app.trust.capability_policy import CapabilityPolicy
from app.trust.capability_role_policy import CapabilityRoleOperationPolicy


class ProductionCapabilityComposition:
    """
    Production composition root for the new capability execution path.

    This object wires together:
      - explicit commercial entitlements,
      - capability authorization,
      - authenticated role authorization,
      - trusted confirmation policy,
      - emergency safety enforcement,
      - concrete capability routing,
      - capability execution.

    It does not replace the legacy AssistantOrchestrator yet.
    """

    def __init__(
        self,
        *,
        entitlement_resolver: ExplicitEntitlementResolver,
        role_policy: CapabilityRoleOperationPolicy,
        operation_policy: CapabilityOperationPolicy,
        router: CapabilityRouter,
        safety_enforcement: SafetyEnforcement,
    ) -> None:
        if not isinstance(
            entitlement_resolver,
            ExplicitEntitlementResolver,
        ):
            raise TypeError(
                "entitlement_resolver must be an "
                "ExplicitEntitlementResolver."
            )

        if not isinstance(
            role_policy,
            CapabilityRoleOperationPolicy,
        ):
            raise TypeError(
                "role_policy must be a CapabilityRoleOperationPolicy."
            )

        if not isinstance(
            operation_policy,
            CapabilityOperationPolicy,
        ):
            raise TypeError(
                "operation_policy must be a CapabilityOperationPolicy."
            )

        if not isinstance(router, CapabilityRouter):
            raise TypeError(
                "router must be a CapabilityRouter."
            )

        if not isinstance(
            safety_enforcement,
            SafetyEnforcement,
        ):
            raise TypeError(
                "safety_enforcement must be a SafetyEnforcement."
            )

        self._entitlement_resolver = entitlement_resolver
        self._role_policy = role_policy
        self._operation_policy = operation_policy
        self._router = router
        self._safety_enforcement = safety_enforcement

    @property
    def operation_policy(self) -> CapabilityOperationPolicy:
        return self._operation_policy

    @property
    def router(self) -> CapabilityRouter:
        return self._router

    def policy_for_business(
        self,
        business_id: str,
    ) -> CapabilityPolicy:
        entitlements = self._entitlement_resolver.resolve(
            business_id
        )

        return CapabilityPolicy.from_entitlements(
            entitlements
        )

    def executor_for_business(
        self,
        business_id: str,
    ) -> CapabilityExecutor:
        return CapabilityExecutor(
            policy=self.policy_for_business(business_id),
            role_policy=self._role_policy,
            router=self._router,
            safety_enforcement=self._safety_enforcement,
        )


def build_production_capability_composition(
    *,
    database,
    capabilities_by_business: Mapping[
        str,
        frozenset[Capability],
    ],
) -> ProductionCapabilityComposition:
    """
    Build the production capability stack.

    Capability grants must be supplied explicitly by the application
    composition layer. No commercial status is converted into grants.
    """

    memory_repository = SQLiteMemoryRepository(database)
    memory_service = ScopedMemoryService(memory_repository)

    entitlement_resolver = ExplicitEntitlementResolver(
        capabilities_by_business
    )

    role_policy = CapabilityRoleOperationPolicy(
        allowed_operations_by_role={
            UserRole.OWNER: {
                Capability.MEMORY: frozenset(
                    {"save", "get", "list", "delete"}
                ),
            },
            UserRole.ADMIN: {
                Capability.MEMORY: frozenset(
                    {"save", "get", "list", "delete"}
                ),
            },
            UserRole.MEMBER: {
                Capability.MEMORY: frozenset(
                    {"save", "get", "list"}
                ),
            },
        }
    )

    operation_policy = CapabilityOperationPolicy(
        confirmation_by_operation={
            Capability.MEMORY: {
                "save": False,
                "get": False,
                "list": False,
                "delete": True,
            },
        }
    )

    router = build_capability_router(memory_service)

    safety_repository = SQLiteSafetyRepository(database)
    safety_enforcement = SafetyEnforcement(
        safety_repository
    )

    return ProductionCapabilityComposition(
        entitlement_resolver=entitlement_resolver,
        role_policy=role_policy,
        operation_policy=operation_policy,
        router=router,
        safety_enforcement=safety_enforcement,
    )
