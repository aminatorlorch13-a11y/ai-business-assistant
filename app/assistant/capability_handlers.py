from __future__ import annotations

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
