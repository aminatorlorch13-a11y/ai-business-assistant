from __future__ import annotations
from pathlib import Path
import os

from collections.abc import Mapping

from app.assistant.capability import Capability
from app.assistant.capability_registry import build_capability_router
from app.assistant.capability_router import CapabilityRouter
from app.forge.job_store import ForgeJobStore
from app.forge.project_repository_store import ForgeProjectRepositoryStore
from app.forge.artifact_store import ForgeArtifactStore
from app.forge.artifact_vault import ForgeArtifactVault
from app.forge.worker import Executor, ForgeWorker
from app.forge.worker_runtime import ForgeWorkerRunner
from app.assistant.structured_processor import StructuredAssistantProcessor
from app.forge.brain_candidate_executor import ForgeBrainCandidateExecutor
from app.commercial.entitlement_resolver import ExplicitEntitlementResolver
from app.persistence.capability_entitlement_repository import (
    SQLiteCapabilityEntitlementRepository,
)
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
        memory_service: ScopedMemoryService,
        forge_job_store: ForgeJobStore | None = None,
        forge_project_repository_store: ForgeProjectRepositoryStore | None = None,
        forge_artifact_store: ForgeArtifactStore | None = None,
        forge_artifact_vault: ForgeArtifactVault | None = None,
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

        if not isinstance(memory_service, ScopedMemoryService):
            raise TypeError(
                "memory_service must be a ScopedMemoryService."
            )

        self._entitlement_resolver = entitlement_resolver
        self._role_policy = role_policy
        self._operation_policy = operation_policy
        self._router = router
        self._safety_enforcement = safety_enforcement
        self._memory_service = memory_service
        if forge_job_store is not None and not isinstance(forge_job_store, ForgeJobStore):
            raise TypeError('forge_job_store must be a ForgeJobStore or None.')
        self._forge_job_store = forge_job_store
        if (
            forge_project_repository_store is not None
            and not isinstance(
                forge_project_repository_store, ForgeProjectRepositoryStore
            )
        ):
            raise TypeError(
                "forge_project_repository_store must be a "
                "ForgeProjectRepositoryStore or None."
            )
        self._forge_project_repository_store = forge_project_repository_store
        if forge_artifact_store is not None and not isinstance(forge_artifact_store, ForgeArtifactStore):
            raise TypeError('forge_artifact_store must be a ForgeArtifactStore or None.')
        if forge_artifact_vault is not None and not isinstance(forge_artifact_vault, ForgeArtifactVault):
            raise TypeError('forge_artifact_vault must be a ForgeArtifactVault or None.')
        self._forge_artifact_store = forge_artifact_store
        self._forge_artifact_vault = forge_artifact_vault

    @property
    def memory_service(self) -> ScopedMemoryService:
        return self._memory_service

    @property
    def forge_job_store(self) -> ForgeJobStore | None:
        return self._forge_job_store

    @property
    def forge_project_repository_store(
        self,
    ) -> ForgeProjectRepositoryStore | None:
        return self._forge_project_repository_store

    @property
    def forge_artifact_store(self) -> ForgeArtifactStore | None:
        return self._forge_artifact_store

    @property
    def forge_artifact_vault(self) -> ForgeArtifactVault | None:
        return self._forge_artifact_vault

    def create_forge_terminal_service(
        self,
        *,
        workspace_root=None,
    ):
        """Create a tenant-scoped virtual terminal service for Forge candidates."""
        if (
            self._forge_job_store is None
            or self._forge_artifact_store is None
            or self._forge_artifact_vault is None
        ):
            raise RuntimeError("Forge persistence is not configured.")
        from app.forge.terminal_service import ForgeTerminalService

        runner_url = os.environ.get("FORGE_RUNNER_URL", "").strip()
        runner_token = os.environ.get("FORGE_RUNNER_TOKEN", "").strip()
        runner_client = None

        if bool(runner_url) != bool(runner_token):
            raise RuntimeError(
                "Configure both FORGE_RUNNER_URL and FORGE_RUNNER_TOKEN."
            )

        if runner_url and runner_token:
            from app.forge.runner.client import ForgeRunnerClient
            runner_client = ForgeRunnerClient(
                base_url=runner_url,
                token=runner_token,
            )

        return ForgeTerminalService(
            job_store=self._forge_job_store,
            artifact_store=self._forge_artifact_store,
            artifact_vault=self._forge_artifact_vault,
            workspace_root=workspace_root,
            runner_client=runner_client,
        )

    def create_forge_worker(
        self,
        executor: Executor,
        *,
        worker_id: str | None = None,
        lease_seconds: int = 60,
    ) -> ForgeWorker:
        if self._forge_job_store is None or self._forge_artifact_vault is None:
            raise RuntimeError('Forge persistence is not configured.')
        return ForgeWorker(
            job_store=self._forge_job_store,
            executor=executor,
            vault=self._forge_artifact_vault,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
        )

    def create_brain_forge_worker(
        self,
        processor: StructuredAssistantProcessor,
        *,
        worker_id: str | None = None,
        lease_seconds: int = 60,
    ) -> ForgeWorker:
        executor = ForgeBrainCandidateExecutor(processor)
        return self.create_forge_worker(
            executor,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
        )

    def start_brain_forge_worker(
        self,
        processor: StructuredAssistantProcessor,
        *,
        worker_id: str | None = None,
        lease_seconds: int = 60,
        poll_interval: float = 1.0,
    ) -> ForgeWorkerRunner:
        worker = self.create_brain_forge_worker(
            processor,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
        )
        return ForgeWorkerRunner(
            worker,
            poll_interval=poll_interval,
        ).start()

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
) -> ProductionCapabilityComposition:
    """
    Build the production capability stack.

    Capability grants must be supplied explicitly by the application
    composition layer. No commercial status is converted into grants.
    """

    memory_repository = SQLiteMemoryRepository(database)
    memory_service = ScopedMemoryService(memory_repository)

    entitlement_repository = SQLiteCapabilityEntitlementRepository(
        database
    )

    entitlement_resolver = ExplicitEntitlementResolver(
        entitlement_repository
    )

    role_policy = CapabilityRoleOperationPolicy(
        allowed_operations_by_role={
            UserRole.OWNER: {
                Capability.MEMORY: frozenset(
                    {"save", "get", "list", "delete"}
                ),
                Capability.FORGE: frozenset(
                    {"submit_job", "get_job", "list_jobs"}
                ),
            },
            UserRole.ADMIN: {
                Capability.MEMORY: frozenset(
                    {"save", "get", "list", "delete"}
                ),
                Capability.FORGE: frozenset(
                    {"submit_job", "get_job", "list_jobs"}
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
                "save": True,
                "get": False,
                "list": False,
                "delete": True,
            },
            Capability.FORGE: {
                "submit_job": True,
                "get_job": False,
                "list_jobs": False,
            },
        }
    )

    forge_job_store = ForgeJobStore(database)
    forge_project_repository_store = ForgeProjectRepositoryStore(database)
    artifact_root = Path(
        os.getenv('FORGE_ARTIFACT_STORAGE_PATH', 'data/forge-artifacts')
    ).expanduser()
    forge_artifact_store = ForgeArtifactStore(database, artifact_root)
    forge_artifact_vault = ForgeArtifactVault(forge_artifact_store)
    router = build_capability_router(
        memory_service,
        forge_job_store=forge_job_store,
    )

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
        memory_service=memory_service,
        forge_job_store=forge_job_store,
        forge_project_repository_store=forge_project_repository_store,
        forge_artifact_vault=forge_artifact_vault,
        forge_artifact_store=forge_artifact_store,
    )
