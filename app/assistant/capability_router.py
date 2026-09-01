from collections.abc import Mapping
from typing import Callable

from app.assistant.capability import Capability, CapabilityRequest


CapabilityHandler = Callable[[CapabilityRequest], object]


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

    def route(self, request: CapabilityRequest) -> object:
        """
        Route a validated capability request to its registered handler.
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

        return handler(request)
