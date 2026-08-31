from app.ai.provider import AIProvider
from app.assistant.interpretation import AIInterpretation
from app.assistant.message import AssistantMessage
from app.assistant.interpretation_validator import AIInterpretationValidator


class AssistantProcessor:
    """Processes incoming business-assistant messages."""

    def __init__(
        self,
        ai_provider: AIProvider,
        validator: AIInterpretationValidator,
    ) -> None:
        self._ai_provider = ai_provider
        self._validator = validator

    def process(self, message: AssistantMessage) -> AIInterpretation:
        """Interpret and validate an incoming assistant message."""

        interpretation = self._ai_provider.interpret(message)

        return self._validator.validate(
            interpretation,
            business_id=message.business_id,
        )
