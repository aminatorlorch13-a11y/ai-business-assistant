from app.assistant.message import AssistantMessage
from app.assistant.orchestrator import AssistantOrchestrator
from app.assistant.response import AssistantResponse
from app.automation.configuration import AutomationConfiguration
from app.automation.context import AutomationContext
from app.automation.event import AutomationEvent
from app.automation.router import AutomationRouter
from app.models.business import Business


class AutomationService:
    """Entry point for business automation events."""

    def __init__(
        self,
        business: Business,
        orchestrator: AssistantOrchestrator,
        configuration: AutomationConfiguration,
    ) -> None:
        if not isinstance(business, Business):
            raise TypeError("business must be a Business.")

        if not isinstance(orchestrator, AssistantOrchestrator):
            raise TypeError(
                "orchestrator must be an AssistantOrchestrator."
            )

        if not isinstance(configuration, AutomationConfiguration):
            raise TypeError(
                "configuration must be an AutomationConfiguration."
            )

        if configuration.business_id != business.business_id:
            raise ValueError(
                "Automation configuration does not belong to this business."
            )

        self._business = business
        self._orchestrator = orchestrator
        self._configuration = configuration

    def handle(
        self,
        event: AutomationEvent,
    ) -> AssistantResponse:
        """Validate, route, and process an automation event."""

        if not isinstance(event, AutomationEvent):
            raise TypeError("event must be an AutomationEvent.")

        if event.business_id != self._business.business_id:
            raise ValueError(
                "Automation event does not belong to this business."
            )

        module = AutomationRouter.module_for(event)

        if not self._configuration.module_enabled(module):
            raise ValueError(
                f"Automation module is disabled: {module}"
            )

        context = AutomationContext.from_event(event)
        message = self._build_message(event)

        return self._orchestrator.handle(
            message,
            automation_context=context,
        )

    @staticmethod
    def _build_message(
        event: AutomationEvent,
    ) -> AssistantMessage:
        """Create a minimal trigger message for an automation event."""

        return AssistantMessage(
            business_id=event.business_id,
            content=f"Automation event: {event.event_type}",
        )
