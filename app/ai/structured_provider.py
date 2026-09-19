from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping

from app.ai.capability_response_parser import AICapabilityResponseParser
from app.ai.context import AIContext
from app.ai.errors import AIProviderError
from app.ai.raw_provider import RawAIProvider
from app.assistant.ai_result import AIResult
from app.assistant.message import AssistantMessage


class StructuredAIProvider(ABC):
    """
    Application-facing provider contract for the new AIResult boundary.

    Providers generate untrusted structured output. The parser converts that
    output into AIResult. This layer does not authorize or execute capability
    requests.
    """

    @abstractmethod
    def generate(
        self,
        message: AssistantMessage,
        context: AIContext,
    ) -> AIResult:
        """Generate and validate a structured AI result."""
        raise NotImplementedError


class ParsedRawAIProvider(StructuredAIProvider):
    """
    Adapts an existing RawAIProvider to the new AIResult contract.

    The raw provider remains responsible only for provider transport and
    extraction. Parsing is performed here at the application boundary.
    """

    def __init__(
        self,
        raw_provider: RawAIProvider,
        parser: AICapabilityResponseParser | None = None,
    ) -> None:
        if not isinstance(raw_provider, RawAIProvider):
            raise TypeError("raw_provider must be a RawAIProvider.")

        if parser is not None and not isinstance(
            parser,
            AICapabilityResponseParser,
        ):
            raise TypeError("parser must be an AICapabilityResponseParser.")

        self._raw_provider = raw_provider
        self._parser = parser or AICapabilityResponseParser()

    def generate(
        self,
        message: AssistantMessage,
        context: AIContext,
    ) -> AIResult:
        if not isinstance(message, AssistantMessage):
            raise TypeError("message must be an AssistantMessage.")

        if not isinstance(context, AIContext):
            raise TypeError("context must be an AIContext.")

        if context.memory_context.business_id != message.business_id:
            raise ValueError(
                "AI context does not belong to this business."
            )

        try:
            raw_response = self._raw_provider.generate(
                message,
                context,
            )
        except Exception as exc:
            if isinstance(exc, AIProviderError):
                raise
            raise AIProviderError("AI provider failed.") from exc

        if not isinstance(raw_response, Mapping):
            raise TypeError("AI provider returned a non-mapping result.")

        return self._parser.parse(raw_response)
