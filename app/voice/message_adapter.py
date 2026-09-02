from app.assistant.message import AssistantMessage
from app.voice.input import ConversationInput


class ConversationMessageAdapter:
    """Converts unified conversation input into an assistant message.

    The business_id is supplied by the trusted application/session boundary.
    User-provided voice or text content cannot choose or override it.
    """

    def to_assistant_message(
        self,
        conversation_input: ConversationInput,
        business_id: str,
    ) -> AssistantMessage:
        if not isinstance(conversation_input, ConversationInput):
            raise TypeError(
                "conversation_input must be a ConversationInput."
            )

        if not isinstance(business_id, str) or not business_id.strip():
            raise ValueError(
                "business_id must be a non-empty string."
            )

        return AssistantMessage(
            business_id=business_id,
            content=conversation_input.text,
        )
