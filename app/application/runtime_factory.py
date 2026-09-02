from app.assistant.orchestrator import AssistantOrchestrator
from app.models.business import Business
from app.models.voice import VoiceConfiguration
from app.voice.conversation_coordinator import (
    AssistantConversationCoordinator,
)
from app.voice.engine import SpeechEngine
from app.voice.input_engine import SpeechInputEngine
from app.voice.message_adapter import ConversationMessageAdapter
from app.voice.service import VoiceService

from app.application.runtime import AssistantRuntime


class AssistantRuntimeFactory:
    """
    Composition boundary for constructing a business assistant runtime.

    Infrastructure dependencies are injected rather than hidden inside
    the runtime. This keeps the application portable across Android,
    desktop, web, cloud, and future speech/AI providers.
    """

    @staticmethod
    def create(
        business: Business,
        orchestrator: AssistantOrchestrator,
        speech_input_engine: SpeechInputEngine,
        speech_engine: SpeechEngine,
        voice_service: VoiceService,
        voice_configuration: VoiceConfiguration,
        message_adapter: ConversationMessageAdapter,
    ) -> AssistantRuntime:
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

        if not isinstance(
            voice_configuration,
            VoiceConfiguration,
        ):
            raise TypeError(
                "voice_configuration must be a VoiceConfiguration."
            )

        if not isinstance(
            message_adapter,
            ConversationMessageAdapter,
        ):
            raise TypeError(
                "message_adapter must be a ConversationMessageAdapter."
            )

        coordinator = AssistantConversationCoordinator(
            business=business,
            orchestrator=orchestrator,
            speech_input_engine=speech_input_engine,
            speech_engine=speech_engine,
            voice_service=voice_service,
            voice_configuration=voice_configuration,
            message_adapter=message_adapter,
        )

        return AssistantRuntime(
            business=business,
            orchestrator=orchestrator,
            conversation_coordinator=coordinator,
        )
