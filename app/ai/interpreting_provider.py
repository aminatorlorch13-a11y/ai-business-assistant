from app.ai.provider import AIProvider
from app.ai.raw_provider import RawAIProvider
from app.ai.response_parser import AIResponseParser
from app.assistant.interpretation import AIInterpretation
from app.assistant.message import AssistantMessage


class InterpretingAIProvider(AIProvider):
    """Converts raw AI output into a structured assistant interpretation."""

    def __init__(
        self,
        raw_provider: RawAIProvider,
        parser: AIResponseParser | None = None,
    ) -> None:
        self._raw_provider = raw_provider
        self._parser = parser or AIResponseParser()

    def interpret(self, message: AssistantMessage) -> AIInterpretation:
        """Generate raw AI output and parse it into an interpretation."""
        raw_response = self._raw_provider.generate(message)

        return self._parser.parse(
            raw_response,
            business_id=message.business_id,
        )
