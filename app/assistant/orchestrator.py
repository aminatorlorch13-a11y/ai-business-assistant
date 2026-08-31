from app.assistant.action_executor import ActionExecutor
from app.assistant.message import AssistantMessage
from app.assistant.processor import AssistantProcessor
from app.assistant.response import AssistantResponse
from app.models.business import Business


class AssistantOrchestrator:
    """Coordinates message processing, authorization, and business actions."""

    def __init__(
        self,
        business: Business,
        processor: AssistantProcessor,
        executor: ActionExecutor,
    ) -> None:
        self._business = business
        self._processor = processor
        self._executor = executor

    def handle(self, message: AssistantMessage) -> AssistantResponse:
        """Process a message and execute its interpreted action."""

        if message.business_id != self._business.business_id:
            raise ValueError("Message does not belong to this business.")

        interpretation = self._processor.process(message)

        if interpretation.intent.business_id != self._business.business_id:
            raise ValueError(
                "AI interpretation does not belong to this business."
            )

        if interpretation.action.business_id != self._business.business_id:
            raise ValueError(
                "AI action does not belong to this business."
            )

        result = self._executor.execute(interpretation.action)

        return AssistantResponse(
            business_id=self._business.business_id,
            assistant_name=self._business.assistant_name,
            message=result,
        )
