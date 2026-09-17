from dataclasses import dataclass

from app.assistant.action import AssistantAction
from app.assistant.intent import AssistantIntent


@dataclass(frozen=True)
class AIInterpretation:
    """Immutable, validated interpretation produced by the AI."""

    intent: AssistantIntent
    action: AssistantAction

    def __post_init__(self) -> None:
        if not isinstance(self.intent, AssistantIntent):
            raise TypeError(
                "intent must be an AssistantIntent."
            )

        if not isinstance(self.action, AssistantAction):
            raise TypeError(
                "action must be an AssistantAction."
            )

        if self.intent.business_id != self.action.business_id:
            raise ValueError(
                "Intent and action must belong to the same business."
            )
