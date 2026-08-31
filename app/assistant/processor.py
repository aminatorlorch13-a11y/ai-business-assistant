from app.ai.provider import AIProvider
from app.assistant.message import AssistantMessage
from app.assistant.response import AssistantResponse


class AssistantProcessor:
    """Processes incoming business-assistant messages."""

    def __init__(self, ai_provider: AIProvider) -> None:
        self._ai_provider = ai_provider

    def process(self, message: AssistantMessage) -> AssistantResponse:
        """Process a message through the configured AI provider."""
        return self._ai_provider.respond(message)
