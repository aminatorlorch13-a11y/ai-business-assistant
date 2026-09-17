from __future__ import annotations

from app.assistant.orchestrator import AssistantOrchestrator
from app.assistant.response import AssistantResponse
from app.models.business import Business
from app.voice.conversation_coordinator import AssistantConversationCoordinator


class AssistantRuntime:
    """
    Business-scoped application runtime.

    This is the application boundary between external entry points and
    the assistant's internal orchestration system.

    Responsibilities:
    - enforce the runtime's business boundary;
    - expose text and voice entry points;
    - delegate conversation processing to the conversation coordinator;
    - expose the conversation session;
    - delegate voice output to the conversation coordinator.

    The runtime does not:
    - interpret AI output;
    - authorize actions;
    - execute business operations directly;
    - contain payment logic;
    - contain provider-specific speech logic;
    - bypass the normal assistant pipeline;
    - own conversation lifecycle transitions.

    Voice and text both enter through the same business-scoped
    conversation boundary.
    """

    def __init__(
        self,
        business: Business,
        orchestrator: AssistantOrchestrator,
        conversation_coordinator: AssistantConversationCoordinator,
    ) -> None:
        if not isinstance(business, Business):
            raise TypeError("business must be a Business.")

        if not isinstance(orchestrator, AssistantOrchestrator):
            raise TypeError(
                "orchestrator must be an AssistantOrchestrator."
            )

        if not isinstance(
            conversation_coordinator,
            AssistantConversationCoordinator,
        ):
            raise TypeError(
                "conversation_coordinator must be an "
                "AssistantConversationCoordinator."
            )

        if (
            conversation_coordinator.session is None
        ):
            raise RuntimeError(
                "Conversation coordinator must provide a session."
            )

        if (
            conversation_coordinator._business.business_id
            != business.business_id
        ):
            raise ValueError(
                "Conversation coordinator does not belong to this business."
            )

        if orchestrator._business.business_id != business.business_id:
            raise ValueError(
                "Orchestrator does not belong to this business."
            )

        self._business = business
        self._orchestrator = orchestrator
        self._conversation_coordinator = conversation_coordinator

    @property
    def business(self) -> Business:
        return self._business

    @property
    def conversation_coordinator(
        self,
    ) -> AssistantConversationCoordinator:
        return self._conversation_coordinator

    @property
    def session(self):
        return self._conversation_coordinator.session

    def handle_text(self, text: str) -> AssistantResponse:
        if not isinstance(text, str):
            raise TypeError("text must be a string.")

        if not text.strip():
            raise ValueError("text must be a non-empty string.")

        return self._conversation_coordinator.process_text_turn(text)

    def handle_voice_turn(self) -> AssistantResponse:
        conversation_input = (
            self._conversation_coordinator.capture_voice_input()
        )

        return self._conversation_coordinator.process_input(
            conversation_input
        )

    def speak_response(
        self,
        response: AssistantResponse,
    ) -> None:
        if not isinstance(response, AssistantResponse):
            raise TypeError(
                "response must be an AssistantResponse."
            )

        if response.business_id != self._business.business_id:
            raise ValueError(
                "Response does not belong to this business."
            )

        self._conversation_coordinator.speak_response(response)

    def run_voice_conversation(self) -> None:
        self._conversation_coordinator.run()
