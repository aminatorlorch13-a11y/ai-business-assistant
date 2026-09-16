from __future__ import annotations

from app.persistence.safety_repository import SQLiteSafetyRepository
from app.safety.models import SafetyControlScope


class SafetyExecutionDenied(PermissionError):
    """Raised when emergency safety controls prohibit execution."""


class SafetyEnforcement:
    """
    Execution-time emergency safety gate.

    This component is deliberately separate from:
      - commercial entitlement
      - action confirmation policy
      - AI reasoning
      - Founder controls

    The executor asks this component whether execution is currently safe.
    Missing controls mean "no halt".
    Failure to determine the safety state means "deny".
    """

    def __init__(self, repository: SQLiteSafetyRepository) -> None:
        if not isinstance(repository, SQLiteSafetyRepository):
            raise TypeError("repository must be a SQLiteSafetyRepository.")
        self._repository = repository

    def require_execution_allowed(self, business_id: str) -> None:
        if not isinstance(business_id, str) or not business_id.strip():
            raise ValueError("business_id must be a non-empty string.")

        business_id = business_id.strip()

        # GLOBAL is checked first because it overrides every business.
        self._require_scope_allowed(
            SafetyControlScope.GLOBAL,
            "platform",
        )

        # A business halt applies only to its target business.
        self._require_scope_allowed(
            SafetyControlScope.BUSINESS,
            business_id,
        )

    def require_capability_allowed(
        self,
        capability: str,
    ) -> None:
        if not isinstance(capability, str) or not capability.strip():
            raise ValueError("capability must be a non-empty string.")

        self._require_scope_allowed(
            SafetyControlScope.CAPABILITY,
            capability.strip(),
        )

    def require_channel_allowed(
        self,
        channel: str,
    ) -> None:
        if not isinstance(channel, str) or not channel.strip():
            raise ValueError("channel must be a non-empty string.")

        self._require_scope_allowed(
            SafetyControlScope.CHANNEL,
            channel.strip(),
        )

    def require_integration_allowed(
        self,
        integration: str,
    ) -> None:
        if not isinstance(integration, str) or not integration.strip():
            raise ValueError("integration must be a non-empty string.")

        self._require_scope_allowed(
            SafetyControlScope.INTEGRATION,
            integration.strip(),
        )

    def _require_scope_allowed(
        self,
        scope: SafetyControlScope,
        target: str,
    ) -> None:
        try:
            control = self._repository.get_active_control(scope, target)
        except Exception as exc:
            # Safety state is security-critical.
            # Never interpret an unavailable safety database as "safe".
            raise SafetyExecutionDenied(
                "Execution blocked because emergency safety state "
                "could not be verified."
            ) from exc

        if control is None:
            return

        raise SafetyExecutionDenied(
            f"Execution blocked by emergency safety control "
            f"{control.control_id!r}."
        )
