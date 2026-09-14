from app.assistant.conversation import ConversationHistory
from app.assistant.message import AssistantMessage
from app.assistant.processor import AssistantProcessor
from app.assistant.response import AssistantResponse
from app.automation.context import AutomationContext
from app.assistant.action_executor import ActionExecutor
from app.identity.tenant import TenantContext
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
        automation_context: AutomationContext | None = None,
        tenant: TenantContext | None = None,
        conversation_history: ConversationHistory | None = None,
    ) -> AssistantResponse:
        """Process a message and execute its interpreted action."""

        if message.business_id != self._business.business_id:
            raise ValueError(
                "Message does not belong to this business."
            )

        if automation_context is not None and not isinstance(
            automation_context,
            AutomationContext,
        ):
            raise TypeError(
                "automation_context must be an AutomationContext or None."
            )

        if (
            automation_context is not None
            and automation_context.business_id != message.business_id
        ):
            raise ValueError(
                "Automation context does not belong to this message business."
            )

        if conversation_history is not None and not isinstance(
            conversation_history,
            ConversationHistory,
        ):
            raise TypeError(
                "conversation_history must be a ConversationHistory or None."
            )

        if (
            conversation_history is not None
            and conversation_history.business_id != message.business_id
        ):
            raise ValueError(
                "Conversation history does not belong to this message business."
            )

        if tenant is not None and not isinstance(tenant, TenantContext):
            raise TypeError(
                "tenant must be a TenantContext or None."
            )

        if (
            tenant is not None
            and tenant.business_id != message.business_id
        ):
            raise ValueError(
                "Execution tenant does not belong to this message business."
            )

        interpretation = self._processor.process(
            message,
            automation_context=automation_context,
            conversation_history=conversation_history,
        )

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
                tenant=tenant,
            )
        else:
            result = self._executor.execute(
                interpretation.action,
                tenant=tenant,
            )

        return AssistantResponse(
            business_id=self._business.business_id,
            assistant_name=self._business.assistant_name,
            message=result,
        )
