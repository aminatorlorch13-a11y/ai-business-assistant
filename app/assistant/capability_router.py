from __future__ import annotations

from collections.abc import Callable, Mapping

from app.assistant.capability import Capability
from app.assistant.execution import (
    CapabilityExecutionRequest,
    CapabilityExecutionResult,
)


CapabilityHandler = Callable[
    [CapabilityExecutionRequest],
    CapabilityExecutionResult,
]


class CapabilityRouter:
    """
    Deterministic registry and router for concrete capability operations.

    The router knows which operations are registered and how to dispatch
    them. It does not perform entitlement, authorization, safety,
    confirmation, or AI reasoning.
    """

    def __init__(
        self,
        handlers: Mapping[
            Capability,
            Mapping[str, CapabilityHandler],
        ],
    ) -> None:
        if not isinstance(handlers, Mapping):
            raise TypeError("handlers must be a mapping.")

        normalized: dict[
            Capability,
            dict[str, CapabilityHandler],
        ] = {}

        for capability, operations in handlers.items():
            if not isinstance(capability, Capability):
                raise TypeError(
                    "handler keys must be Capability values."
                )

            if not isinstance(operations, Mapping):
                raise TypeError(
                    "operations for each capability must be a mapping."
                )

            normalized_operations: dict[str, CapabilityHandler] = {}

            for operation, handler in operations.items():
                if not isinstance(operation, str):
                    raise TypeError(
                        "operation names must be strings."
                    )

                operation = operation.strip()

                if not operation:
                    raise ValueError(
                        "operation names must be non-empty strings."
                    )

                if not callable(handler):
                    raise TypeError(
                        "capability operation handlers must be callable."
                    )

                normalized_operations[operation] = handler

            normalized[capability] = normalized_operations

        self._handlers = normalized

    def supports(self, capability: Capability) -> bool:
        if not isinstance(capability, Capability):
            raise TypeError("capability must be a Capability.")

        return capability in self._handlers

    def supports_operation(
        self,
        capability: Capability,
        operation: str,
    ) -> bool:
        if not isinstance(capability, Capability):
            raise TypeError("capability must be a Capability.")

        if not isinstance(operation, str):
            raise TypeError("operation must be a string.")

        operation = operation.strip()

        if not operation:
            raise ValueError(
                "operation must be a non-empty string."
            )

        return operation in self._handlers.get(capability, {})

    def route(
        self,
        request: CapabilityExecutionRequest,
    ) -> CapabilityExecutionResult:
        if not isinstance(request, CapabilityExecutionRequest):
            raise TypeError(
                "request must be a CapabilityExecutionRequest."
            )

        operations = self._handlers.get(request.capability)

        if operations is None:
            raise LookupError(
                f"No handlers registered for capability "
                f"'{request.capability.value}'."
            )

        handler = operations.get(request.operation)

        if handler is None:
            raise LookupError(
                f"No handler registered for operation "
                f"'{request.operation}' under capability "
                f"'{request.capability.value}'."
            )

        result = handler(request)

        if not isinstance(result, CapabilityExecutionResult):
            raise TypeError(
                "capability operation handler must return a "
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
