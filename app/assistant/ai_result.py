from __future__ import annotations

from dataclasses import dataclass

from app.assistant.ai_capability_request import AICapabilityRequest


@dataclass(frozen=True)
class AIResult:
    """
    Structured result produced at the AI application boundary.

    This object separates natural-language conversation from executable
    capability proposals.

    The AI may provide:
    - a conversational response, and/or
    - one or more untrusted capability requests.

    Capability requests are proposals only. They do not grant authorization,
    identify a tenant, select handlers, or report execution success.
    """

    response: str | None = None
    capability_requests: tuple[AICapabilityRequest, ...] = ()

    def __post_init__(self) -> None:
        if self.response is not None:
            if not isinstance(self.response, str):
                raise TypeError("response must be a string or None.")
            normalized_response = self.response.strip()
            if not normalized_response:
                raise ValueError("response must be non-empty when provided.")
            object.__setattr__(self, "response", normalized_response)

        if not isinstance(self.capability_requests, tuple):
            raise TypeError("capability_requests must be a tuple.")

        for request in self.capability_requests:
            if not isinstance(request, AICapabilityRequest):
                raise TypeError(
                    "capability_requests must contain only "
                    "AICapabilityRequest objects."
                )

        if self.response is None and not self.capability_requests:
            raise ValueError(
                "AIResult must contain a response or at least one "
                "capability request."
            )
