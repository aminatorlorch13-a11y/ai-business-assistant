from app.assistant.action import AssistantAction
from app.services.business_operation import BusinessOperation


class AssistantConversationOperation(BusinessOperation):
    """
    Handles general conversation actions (target: 'assistant').

    The reply text itself is produced upstream by the AI provider as
    action.instruction. This operation's job is only to enforce that
    it is being invoked for the correct target and hand that text
    back as the executed result.
    """

    def execute(self, action: AssistantAction) -> str:
        """Return the AI-authored conversational reply."""

        if action.target != "assistant":
            raise ValueError(
                "AssistantConversationOperation requires an "
                "'assistant' target."
            )

        return action.instruction
