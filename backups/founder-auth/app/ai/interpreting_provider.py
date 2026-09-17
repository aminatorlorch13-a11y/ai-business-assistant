from app.ai.context import AIContext
from app.ai.errors import AIProviderError
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
        if not isinstance(raw_provider, RawAIProvider):
            raise TypeError("raw_provider must be a RawAIProvider.")

        self._raw_provider = raw_provider
        self._parser = parser or AIResponseParser()

    def interpret(
        self,
        message: AssistantMessage,
        context: AIContext,
    ) -> AIInterpretation:
        """Generate raw AI output and parse it into an interpretation."""
        if not isinstance(message, AssistantMessage):
            raise TypeError("message must be an AssistantMessage.")

        if not isinstance(context, AIContext):
            raise TypeError("context must be an AIContext.")

        if context.memory_context.business_id != message.business_id:
            raise ValueError("AI context does not belong to this business.")

        try:
            raw_response = self._raw_provider.generate(
                message,
                context,
            )
        except Exception as exc:
            if isinstance(exc, AIProviderError):
                raise
            raise AIProviderError("AI provider failed.") from exc

        return self._parser.parse(
            raw_response,
            business_id=message.business_id,
        )
