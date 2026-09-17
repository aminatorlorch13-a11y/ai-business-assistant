from dataclasses import dataclass

from app.assistant.action import AssistantAction


@dataclass(frozen=True)
class ActionPolicy:
    """Defines which action types a business assistant may perform."""

    allow_create: bool = True
    allow_update: bool = True
    allow_delete: bool = False

    def allows(self, action: AssistantAction) -> bool:
        """Return whether the policy permits the supplied action."""

        if action.action_type == "none":
            return True

        if action.action_type == "create":
            return self.allow_create

        if action.action_type == "update":
            return self.allow_update

        if action.action_type == "delete":
            return self.allow_delete

        return False
