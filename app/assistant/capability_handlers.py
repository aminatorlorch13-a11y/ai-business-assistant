from __future__ import annotations

from datetime import datetime, timezone

from app.forge.job import ForgeJob
from app.forge.job_store import ForgeJobStore
from app.forge.task_spec import ForgeTaskSpec

from collections.abc import Mapping
from typing import Any

from app.assistant.capability import Capability
from app.assistant.execution import (
    CapabilityExecutionRequest,
    CapabilityExecutionResult,
)
from app.memory.scoped_service import ScopedMemoryService
from app.models.memory import Memory


class MemoryCapabilityHandlers:
    """Production handlers for the persistent business-memory capability."""

    def __init__(self, memory_service: ScopedMemoryService) -> None:
        if not isinstance(memory_service, ScopedMemoryService):
            raise TypeError(
                "memory_service must be a ScopedMemoryService."
            )
        self._memory_service = memory_service

    def save(
        self,
        request: CapabilityExecutionRequest,
    ) -> CapabilityExecutionResult:
        self._require_request(request, "save")
        self._require_arguments(
            request.arguments,
            {"memory_id", "content", "memory_type", "importance"},
        )

        memory = Memory(
            memory_id=self._require_string(
                request.arguments,
                "memory_id",
            ),
            business_id=request.business_id,
            content=self._require_string(
                request.arguments,
                "content",
            ),
            memory_type=self._require_string(
                request.arguments,
                "memory_type",
            ),
            importance=self._require_int(
                request.arguments,
                "importance",
            ),
        )

        saved = self._memory_service.save(memory)

        return CapabilityExecutionResult(
            success=True,
            capability=Capability.MEMORY,
            operation="save",
            business_id=request.business_id,
            data=saved,
            verification="Memory was persisted for the trusted business.",
        )

    def get(
        self,
        request: CapabilityExecutionRequest,
    ) -> CapabilityExecutionResult:
        self._require_request(request, "get")
        self._require_arguments(request.arguments, {"memory_id"})

        memory = self._memory_service.get(
            request.business_id,
            self._require_string(request.arguments, "memory_id"),
        )

        return CapabilityExecutionResult(
            success=True,
            capability=Capability.MEMORY,
            operation="get",
            business_id=request.business_id,
            data=memory,
            verification=(
                "Memory lookup was performed within the trusted "
                "business scope."
            ),
        )

    def list(
        self,
        request: CapabilityExecutionRequest,
    ) -> CapabilityExecutionResult:
        self._require_request(request, "list")
        self._require_arguments(request.arguments, set())

        memories = self._memory_service.list_for_business(
            request.business_id
        )

        return CapabilityExecutionResult(
            success=True,
            capability=Capability.MEMORY,
            operation="list",
            business_id=request.business_id,
            data=tuple(memories),
            verification=(
                "Memory listing was performed within the trusted "
                "business scope."
            ),
        )

    def delete(
        self,
        request: CapabilityExecutionRequest,
    ) -> CapabilityExecutionResult:
        self._require_request(request, "delete")
        self._require_arguments(request.arguments, {"memory_id"})

        deleted = self._memory_service.delete(
            request.business_id,
            self._require_string(request.arguments, "memory_id"),
        )

        return CapabilityExecutionResult(
            success=True,
            capability=Capability.MEMORY,
            operation="delete",
            business_id=request.business_id,
            data=deleted,
            verification=(
                "Memory deletion was attempted within the trusted "
                "business scope."
            ),
        )

    @staticmethod
    def _require_request(
        request: CapabilityExecutionRequest,
        operation: str,
    ) -> None:
        if not isinstance(request, CapabilityExecutionRequest):
            raise TypeError(
                "request must be a CapabilityExecutionRequest."
            )

        if request.capability is not Capability.MEMORY:
            raise ValueError(
                "Memory handlers only accept the memory capability."
            )

        if request.operation != operation:
            raise ValueError(
                f"Memory handler received operation '{request.operation}', "
                f"expected '{operation}'."
            )

    @staticmethod
    def _require_arguments(
        arguments: Mapping[str, Any],
        expected: set[str],
    ) -> None:
        if not isinstance(arguments, Mapping):
            raise TypeError("request.arguments must be a mapping.")

        actual = set(arguments)

        missing = expected - actual
        if missing:
            raise ValueError(
                "Missing required memory arguments: "
                + ", ".join(sorted(missing))
                + "."
            )

        unexpected = actual - expected
        if unexpected:
            raise ValueError(
                "Unexpected memory arguments: "
                + ", ".join(sorted(unexpected))
                + "."
            )

    @staticmethod
    def _require_string(
        arguments: Mapping[str, Any],
        name: str,
    ) -> str:
        value = arguments[name]

        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"{name} must be a non-empty string."
            )

        return value

    @staticmethod
    def _require_int(
        arguments: Mapping[str, Any],
        name: str,
    ) -> int:
        value = arguments[name]

        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(
                f"{name} must be an integer."
            )

        return value


class ForgeCapabilityHandlers:
    """Tenant-scoped Brain handlers for creating and inspecting Forge jobs."""

    def __init__(self, job_store: ForgeJobStore) -> None:
        if not isinstance(job_store, ForgeJobStore):
            raise TypeError("job_store must be a ForgeJobStore.")
        self._job_store = job_store

    def submit_job(
        self, request: CapabilityExecutionRequest
    ) -> CapabilityExecutionResult:
        self._require_request(request, "submit_job")
        self._require_arguments(
            request.arguments,
            {
                "project_id", "job_id", "job_type", "instructions",
                "scope", "acceptance_criteria",
            },
            optional={"language"},
        )

        project_id = self._require_string(request.arguments, "project_id")
        job_id = self._require_string(request.arguments, "job_id")
        job_type = self._require_string(request.arguments, "job_type")
        instructions = self._require_string(request.arguments, "instructions")
        scope = self._require_string_tuple(request.arguments, "scope")
        criteria = self._require_string_tuple(
            request.arguments, "acceptance_criteria"
        )

        now = datetime.now(timezone.utc)
        job = ForgeJob(
            job_id=job_id,
            business_id=request.business_id,
            project_id=project_id,
            job_type=job_type,
            created_at=now,
            updated_at=now,
        )
        spec = ForgeTaskSpec(
            business_id=request.business_id,
            project_id=project_id,
            job_id=job_id,
            instructions=instructions,
            scope=scope,
            acceptance_criteria=criteria,
            language=request.arguments.get("language", "python"),
        )
        record = self._job_store.create_with_spec(job, spec)

        return CapabilityExecutionResult(
            success=True,
            capability=Capability.FORGE,
            operation="submit_job",
            business_id=request.business_id,
            data=record.job,
            verification=(
                "Forge job and immutable task specification were persisted. "
                "The job is queued; execution has not started."
            ),
        )

    def get_job(
        self, request: CapabilityExecutionRequest
    ) -> CapabilityExecutionResult:
        self._require_request(request, "get_job")
        self._require_arguments(
            request.arguments, {"project_id", "job_id"}
        )
        record = self._job_store.get(
            request.business_id,
            self._require_string(request.arguments, "project_id"),
            self._require_string(request.arguments, "job_id"),
        )
        return CapabilityExecutionResult(
            success=True,
            capability=Capability.FORGE,
            operation="get_job",
            business_id=request.business_id,
            data=None if record is None else record.job,
            verification="Forge job lookup was restricted to the trusted business.",
        )

    def list_jobs(
        self, request: CapabilityExecutionRequest
    ) -> CapabilityExecutionResult:
        self._require_request(request, "list_jobs")
        self._require_arguments(request.arguments, {"project_id"})
        records = self._job_store.list_for_project(
            request.business_id,
            self._require_string(request.arguments, "project_id"),
        )
        return CapabilityExecutionResult(
            success=True,
            capability=Capability.FORGE,
            operation="list_jobs",
            business_id=request.business_id,
            data=tuple(record.job for record in records),
            verification="Forge jobs were listed within the trusted business and project.",
        )

    @staticmethod
    def _require_request(
        request: CapabilityExecutionRequest, operation: str
    ) -> None:
        if not isinstance(request, CapabilityExecutionRequest):
            raise TypeError("request must be a CapabilityExecutionRequest.")
        if request.capability is not Capability.FORGE:
            raise ValueError("Forge handlers only accept the Forge capability.")
        if request.operation != operation:
            raise ValueError(
                f"Forge handler received operation '{request.operation}', "
                f"expected '{operation}'."
            )

    @staticmethod
    def _require_arguments(
        arguments: Mapping[str, Any],
        expected: set[str],
        optional: set[str] | None = None,
    ) -> None:
        if not isinstance(arguments, Mapping):
            raise TypeError("request.arguments must be a mapping.")
        optional = optional or set()
        missing = expected - set(arguments)
        unexpected = set(arguments) - expected - optional
        if missing:
            raise ValueError(
                "Missing required Forge arguments: " + ", ".join(sorted(missing))
            )
        if unexpected:
            raise ValueError(
                "Unexpected Forge arguments: " + ", ".join(sorted(unexpected))
            )

    @staticmethod
    def _require_string(arguments: Mapping[str, Any], name: str) -> str:
        value = arguments[name]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string.")
        return value

    @classmethod
    def _require_string_tuple(
        cls, arguments: Mapping[str, Any], name: str
    ) -> tuple[str, ...]:
        value = arguments[name]
        if not isinstance(value, (list, tuple)):
            raise TypeError(f"{name} must be a list or tuple of strings.")
        if any(not isinstance(item, str) for item in value):
            raise TypeError(f"Every {name} item must be a string.")
        return tuple(value)
