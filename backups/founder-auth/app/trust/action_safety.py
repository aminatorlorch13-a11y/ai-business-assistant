from dataclasses import dataclass

from app.assistant.action import AssistantAction


@dataclass(frozen=True)
class ActionSafetyPolicy:
    """Determines whether an assistant action requires confirmation."""

    require_confirmation_for_create: bool = True
    require_confirmation_for_update: bool = True
    require_confirmation_for_delete: bool = True

    def requires_confirmation(self, action: AssistantAction) -> bool:
        """Return whether the supplied action requires human confirmation."""

        if action.action_type == "none":
            return False

        if action.action_type == "create":
            return self.require_confirmation_for_create

        if action.action_type == "update":
            return self.require_confirmation_for_update

        if action.action_type == "delete":
            return self.require_confirmation_for_delete

        raise ValueError(
            f"Unknown action type: {action.action_type}"
        )
