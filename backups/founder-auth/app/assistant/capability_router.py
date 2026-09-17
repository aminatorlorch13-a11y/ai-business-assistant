from collections.abc import Mapping
from typing import Callable

from app.assistant.capability import (
    Capability,
    CapabilityRequest,
    CapabilityResult,
)


CapabilityHandler = Callable[[CapabilityRequest], CapabilityResult]


class CapabilityRouter:
    """
    Routes authorized high-level capability requests to handlers.

    The router deliberately knows nothing about:
    - email
    - WhatsApp
    - Facebook
    - web browsers
    - databases
    - voice engines

    Those concerns belong behind capability-specific services.
    """

    def __init__(
        self,
        handlers: Mapping[Capability, CapabilityHandler],
    ) -> None:
        if not isinstance(handlers, Mapping):
            raise TypeError("handlers must be a mapping.")

        normalized_handlers = dict(handlers)

        for capability, handler in normalized_handlers.items():
            if not isinstance(capability, Capability):
                raise TypeError(
                    "handler keys must be Capability values."
                )

            if not callable(handler):
                raise TypeError(
                    "each capability handler must be callable."
                )

        self._handlers = normalized_handlers

    def supports(self, capability: Capability) -> bool:
        """
        Return whether a capability currently has a handler.
        """
        if not isinstance(capability, Capability):
            raise TypeError("capability must be a Capability.")

        return capability in self._handlers

    def route(self, request: CapabilityRequest) -> CapabilityResult:
        """
        Route a validated capability request to its registered handler.

        Handler output is validated at the router boundary so arbitrary
        objects cannot silently enter the assistant pipeline.
        """
        if not isinstance(request, CapabilityRequest):
            raise TypeError(
                "request must be a CapabilityRequest."
            )

        handler = self._handlers.get(request.capability)

        if handler is None:
            raise LookupError(
                f"No handler registered for capability "
                f"'{request.capability.value}'."
            )

        result = handler(request)

        if not isinstance(result, CapabilityResult):
            raise TypeError(
                "capability handler must return a CapabilityResult."
            )

        if result.capability is not request.capability:
            raise ValueError(
                "Capability result does not match the request capability."
            )

        if result.business_id != request.business_id:
            raise ValueError(
                "Capability result does not belong to the request business."
            )

        return result
