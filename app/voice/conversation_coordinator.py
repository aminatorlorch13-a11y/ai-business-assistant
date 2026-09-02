from abc import ABC, abstractmethod

from app.assistant.orchestrator import AssistantOrchestrator
from app.assistant.response import AssistantResponse
from app.models.business import Business
from app.models.voice import VoiceConfiguration
from app.voice.conversation import ConversationState
from app.voice.engine import SpeechEngine
from app.voice.input import ConversationInput, ConversationInputSource
from app.voice.input_engine import SpeechInputEngine
from app.voice.message_adapter import ConversationMessageAdapter
from app.voice.service import VoiceService
from app.voice.session import ConversationSession
from app.voice.speech_input import SpeechInput


class ConversationCoordinator(ABC):
    @abstractmethod
    def run(self) -> None:
        raise NotImplementedError


class AssistantConversationCoordinator(ConversationCoordinator):
    """
    Coordinates continuous voice/text conversation for one business.

    Conversation input always enters the normal assistant pipeline.
    Voice does not bypass interpretation, validation, authorization,
    or execution safeguards.

    Session lifecycle transitions are owned by ConversationSession.
    Natural-language commands such as "stop" are not interpreted here
    as low-level session termination. They first pass through the
    normal assistant command pipeline.

    The coordinator also respects terminal session state changes that
    occur during downstream operations such as speech output.
    """

    def __init__(
        self,
        business: Business,
        orchestrator: AssistantOrchestrator,
        speech_input_engine: SpeechInputEngine,
        speech_engine: SpeechEngine,
        voice_service: VoiceService,
        voice_configuration: VoiceConfiguration,
        message_adapter: ConversationMessageAdapter,
        session: ConversationSession | None = None,
    ) -> None:
        if not isinstance(business, Business):
            raise TypeError("business must be a Business.")

        if not isinstance(orchestrator, AssistantOrchestrator):
            raise TypeError(
                "orchestrator must be an AssistantOrchestrator."
            )

        if not isinstance(speech_input_engine, SpeechInputEngine):
            raise TypeError(
                "speech_input_engine must be a SpeechInputEngine."
            )

        if not isinstance(speech_engine, SpeechEngine):
            raise TypeError(
                "speech_engine must be a SpeechEngine."
            )

        if not isinstance(voice_service, VoiceService):
            raise TypeError(
                "voice_service must be a VoiceService."
            )

        if not isinstance(voice_configuration, VoiceConfiguration):
            raise TypeError(
                "voice_configuration must be a VoiceConfiguration."
            )

        if not isinstance(message_adapter, ConversationMessageAdapter):
            raise TypeError(
                "message_adapter must be a ConversationMessageAdapter."
            )

        if session is not None and not isinstance(
            session,
            ConversationSession,
        ):
            raise TypeError(
                "session must be a ConversationSession when provided."
            )

        self._business = business
        self._orchestrator = orchestrator
        self._speech_input_engine = speech_input_engine
        self._speech_engine = speech_engine
        self._voice_service = voice_service
        self._voice_configuration = voice_configuration
        self._message_adapter = message_adapter
        self._session = session or ConversationSession()

    @property
    def session(self) -> ConversationSession:
        return self._session

    def process_input(
        self,
        conversation_input: ConversationInput,
    ) -> AssistantResponse:
        if not isinstance(conversation_input, ConversationInput):
            raise TypeError(
                "conversation_input must be a ConversationInput."
            )

        assistant_message = self._message_adapter.to_assistant_message(
            conversation_input,
            self._business.business_id,
        )

        return self._orchestrator.handle(assistant_message)

    def speak_response(
        self,
        response: AssistantResponse,
    ) -> None:
        if not isinstance(response, AssistantResponse):
            raise TypeError(
                "response must be an AssistantResponse."
            )

        speech_request = self._voice_service.create_speech_request(
            response,
            self._voice_configuration,
        )

        self._speech_engine.speak(speech_request)

    def capture_voice_input(self) -> ConversationInput:
        speech_input = self._speech_input_engine.listen()

        if not isinstance(speech_input, SpeechInput):
            raise TypeError(
                "Speech input engine must return a SpeechInput."
            )

        return ConversationInput(
            text=speech_input.text,
            source=ConversationInputSource.VOICE,
        )

    def process_text_turn(self, text: str) -> AssistantResponse:
        return self.process_input(
            ConversationInput(
                text=text,
                source=ConversationInputSource.TEXT,
            )
        )

    def run(self) -> None:
        """
        Run continuous voice conversation until the session ends.

        A terminal session state reached during a downstream operation
        is respected immediately. The coordinator never attempts to
        transition an already-ended session back into an active state
        or into an error state.
        """
        if self._session.state == ConversationState.ENDED:
            raise RuntimeError(
                "Cannot run an ended conversation."
            )

        while self._session.state != ConversationState.ENDED:
            try:
                self._session.start_listening()

                conversation_input = self.capture_voice_input()

                self._session.start_processing()

                response = self.process_input(
                    conversation_input
                )

                self._session.start_speaking()

                self.speak_response(response)

                if self._session.state == ConversationState.ENDED:
                    break

                self._session.wait_for_input()

            except Exception:
                if self._session.state != ConversationState.ENDED:
                    self._session.fail()
                raise
