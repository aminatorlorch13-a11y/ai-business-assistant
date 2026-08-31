from app.assistant.message import AssistantMessage
from app.assistant.processor import AssistantProcessor
from app.assistant.response import AssistantResponse
from app.assistant.action_executor import ActionExecutor
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

    def handle(
        self,
        message: AssistantMessage,
        confirmed: bool = False,
    ) -> AssistantResponse:
        """Process a message and execute its interpreted action."""

        if message.business_id != self._business.business_id:
            raise ValueError("Message does not belong to this business.")

        interpretation = self._processor.process(message)

        if interpretation.intent.business_id != self._business.business_id:
            raise ValueError(
                "AI interpretation intent does not belong to this business."
            )

        if interpretation.action.business_id != self._business.business_id:
            raise ValueError(
                "AI interpretation action does not belong to this business."
            )

        if confirmed:
            result = self._executor.execute(
                interpretation.action,
                confirmed=True,
            )
        else:
            result = self._executor.execute(
                interpretation.action,
            )

        return AssistantResponse(
            business_id=self._business.business_id,
            assistant_name=self._business.assistant_name,
            message=result,
        )
