from __future__ import annotations

from app.assistant.ai_capability_request import AICapabilityRequest
from app.assistant.execution import CapabilityExecutionRequest


class CapabilityExecutionPreparer:
    """
    Converts an untrusted AI capability proposal into a trusted execution
    request using application-owned execution context.

    This class does not authorize or execute capabilities. Authorization,
    safety enforcement, operation routing, and execution remain the
    responsibility of CapabilityExecutor.
    """

    def prepare(
        self,
        request: AICapabilityRequest,
        *,
        business_id: str,
        channel: str | None = None,
        integration: str | None = None,
    ) -> CapabilityExecutionRequest:
        if not isinstance(request, AICapabilityRequest):
            raise TypeError(
                "request must be an AICapabilityRequest."
            )

        if not isinstance(business_id, str) or not business_id.strip():
            raise ValueError(
                "business_id must be a non-empty string."
            )

        if channel is not None and (
            not isinstance(channel, str) or not channel.strip()
        ):
            raise ValueError(
                "channel must be a non-empty string when provided."
            )

        if integration is not None and (
            not isinstance(integration, str) or not integration.strip()
        ):
            raise ValueError(
                "integration must be a non-empty string when provided."
            )

        return CapabilityExecutionRequest(
            capability=request.capability,
            operation=request.operation,
            business_id=business_id.strip(),
            arguments=request.arguments,
            reason=request.reason,
            channel=channel.strip() if channel is not None else None,
            integration=(
                integration.strip()
                if integration is not None
                else None
            ),
        )
