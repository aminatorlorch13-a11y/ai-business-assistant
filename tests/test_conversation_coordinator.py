import pytest

from app.ai.provider import AIProvider
from app.assistant.action import AssistantAction
from app.assistant.action_executor import ActionExecutor
from app.assistant.interpretation import AIInterpretation
from app.assistant.interpretation_validator import AIInterpretationValidator
from app.assistant.intent import AssistantIntent
from app.assistant.orchestrator import AssistantOrchestrator
from app.assistant.processor import AssistantProcessor
from app.assistant.response import AssistantResponse
from app.models.business import Business
from app.models.voice import VoiceConfiguration
from app.services.business_operation import BusinessOperation
from app.trust.action_policy import ActionPolicy
from app.voice.conversation import ConversationState
from app.voice.conversation_coordinator import (
    AssistantConversationCoordinator as _ProductionAssistantConversationCoordinator,
)
from tests.runtime_support import make_runtime_dependencies


class AssistantConversationCoordinator(_ProductionAssistantConversationCoordinator):
    """Test adapter that supplies real runtime dependencies to the production coordinator."""

    def __init__(self, *args, **kwargs):
        business = kwargs.get("business")
        if business is None and args:
            business = args[0]

        if business is None:
            raise AssertionError(
                "Test coordinator construction requires a business."
            )

        self._runtime_dependencies = make_runtime_dependencies(business.business_id)
        commercial_access = self._runtime_dependencies.commercial_access
        tenant = self._runtime_dependencies.tenant

        kwargs.setdefault("commercial_access", commercial_access)
        kwargs.setdefault("tenant", tenant)

        super().__init__(*args, **kwargs)


from app.voice.engine import SpeechEngine
from app.voice.input import ConversationInput, ConversationInputSource
from app.voice.input_engine import SpeechInputEngine
from app.voice.message_adapter import ConversationMessageAdapter
from app.voice.service import VoiceService
from app.voice.session import ConversationSession
from app.voice.speech_input import SpeechInput


class RecordingAIProvider(AIProvider):
    def __init__(self, response_text="AI response"):
        self.messages = []
        self.response_text = response_text

    def interpret(self, message):
        self.messages.append(message)

        intent = AssistantIntent(
            business_id=message.business_id,
            intent_type="general_question",
            instruction=message.content,
        )

        action = AssistantAction(
            business_id=message.business_id,
            action_type="none",
            target="assistant",
            instruction=self.response_text,
        )

        return AIInterpretation(
            intent=intent,
            action=action,
        )


class RecordingBusinessOperation(BusinessOperation):
    def __init__(self):
        self.actions = []

    def execute(self, action, tenant=None):
        self.actions.append(action)
        return action.instruction


class RecordingSpeechInputEngine(SpeechInputEngine):
    def __init__(self, inputs):
        self.inputs = list(inputs)
        self.calls = 0

    def listen(self):
        self.calls += 1

        if not self.inputs:
            raise RuntimeError("No more speech input configured.")

        return SpeechInput(text=self.inputs.pop(0))


class RecordingSpeechEngine(SpeechEngine):
    def __init__(self):
        self.requests = []

    def speak(self, request):
        self.requests.append(request)

    def cancel_current(self):
        return None


class InvalidSpeechInputEngine(SpeechInputEngine):
    def listen(self):
        return object()


class StopAfterTurnsSpeechEngine(RecordingSpeechEngine):
    def __init__(self, session, stop_after):
        super().__init__()
        self.session = session
        self.stop_after = stop_after

    def speak(self, request):
        super().speak(request)

        if len(self.requests) >= self.stop_after:
            self.session.stop()


def make_business(business_id="business-123"):
    return Business(
        business_id=business_id,
        name="Test Business",
        owner_name="Test Owner",
        assistant_name="Configured Test Assistant",
        assistant_voice="female",
    )


def make_action_executor():
    return ActionExecutor(
        policy=ActionPolicy(),
        operation=RecordingBusinessOperation(),
    )


def make_coordinator(
    *,
    speech_inputs=None,
    session=None,
    response_text="AI response",
    speech_engine=None,
):
    business = make_business()

    provider = RecordingAIProvider(
        response_text=response_text,
    )

    processor = AssistantProcessor(
        ai_provider=provider,
        validator=AIInterpretationValidator(),
    )

    orchestrator = AssistantOrchestrator(
        business=business,
        processor=processor,
        executor=make_action_executor(),
    )

    speech_input_engine = RecordingSpeechInputEngine(
        speech_inputs or ["Hello assistant."],
    )

    if speech_engine is None:
        speech_engine = RecordingSpeechEngine()

    coordinator = AssistantConversationCoordinator(
        business=business,
        orchestrator=orchestrator,
        speech_input_engine=speech_input_engine,
        speech_engine=speech_engine,
        voice_service=VoiceService(),
        voice_configuration=VoiceConfiguration(
            voice="female",
            speed=1.0,
        ),
        message_adapter=ConversationMessageAdapter(),
        session=session,
    )

    return (
        coordinator,
        provider,
        speech_input_engine,
        speech_engine,
    )


def test_capture_voice_input_returns_voice_conversation_input():
    coordinator, _, speech_input_engine, _ = make_coordinator(
        speech_inputs=["Hello assistant."],
    )

    conversation_input = coordinator.capture_voice_input()

    assert isinstance(conversation_input, ConversationInput)
    assert conversation_input.text == "Hello assistant."
    assert conversation_input.source is ConversationInputSource.VOICE
    assert speech_input_engine.calls == 1
    assert coordinator.session.state is ConversationState.IDLE


def test_process_input_uses_trusted_business_boundary():
    coordinator, provider, _, _ = make_coordinator(
        response_text="Hello from Configured Test Assistant.",
    )

    conversation_input = ConversationInput(
        text="Hello assistant.",
        source=ConversationInputSource.VOICE,
    )

    response = coordinator.process_input(conversation_input)

    assert isinstance(response, AssistantResponse)
    assert response.business_id == "business-123"
    assert response.message == "Hello from Configured Test Assistant."

    assert len(provider.messages) == 1
    assert provider.messages[0].business_id == "business-123"
    assert provider.messages[0].content == "Hello assistant."


def test_process_text_turn_uses_same_conversation_pipeline():
    coordinator, provider, _, _ = make_coordinator(
        response_text="Text response.",
    )

    response = coordinator.process_text_turn("Hello by text.")

    assert isinstance(response, AssistantResponse)
    assert response.business_id == "business-123"
    assert response.message == "Text response."

    assert len(provider.messages) == 1
    assert provider.messages[0].business_id == "business-123"
    assert provider.messages[0].content == "Hello by text."


def test_voice_and_text_inputs_share_same_business_boundary():
    coordinator, provider, _, _ = make_coordinator(
        response_text="Shared response.",
    )

    text_input = ConversationInput(
        text="Text message.",
        source=ConversationInputSource.TEXT,
    )

    voice_input = ConversationInput(
        text="Voice message.",
        source=ConversationInputSource.VOICE,
    )

    coordinator.process_input(text_input)
    coordinator.process_input(voice_input)

    assert len(provider.messages) == 2
    assert provider.messages[0].business_id == "business-123"
    assert provider.messages[1].business_id == "business-123"


def test_generic_stop_is_not_directly_treated_as_shutdown():
    coordinator, provider, _, _ = make_coordinator(
        speech_inputs=["stop"],
        response_text="I will pause.",
    )

    conversation_input = coordinator.capture_voice_input()
    response = coordinator.process_input(conversation_input)

    assert response.message == "I will pause."
    assert provider.messages[0].content == "stop"

    assert coordinator.session.state is ConversationState.IDLE


def test_stop_can_be_followed_by_another_conversation_turn():
    session = ConversationSession()

    speech_engine = StopAfterTurnsSpeechEngine(
        session=session,
        stop_after=2,
    )

    coordinator, provider, speech_input_engine, _ = make_coordinator(
        speech_inputs=[
            "stop",
            "Hello assistant.",
        ],
        session=session,
        response_text="Acknowledged.",
        speech_engine=speech_engine,
    )

    coordinator.run()

    assert session.state is ConversationState.ENDED

    assert speech_input_engine.calls == 2

    assert len(provider.messages) == 2
    assert provider.messages[0].content == "stop"
    assert provider.messages[1].content == "Hello assistant."

    assert len(speech_engine.requests) == 2
    assert speech_engine.requests[0].text == "Acknowledged."
    assert speech_engine.requests[1].text == "Acknowledged."


def test_run_processes_multiple_turns_until_explicit_session_stop():
    session = ConversationSession()

    speech_engine = StopAfterTurnsSpeechEngine(
        session=session,
        stop_after=3,
    )

    coordinator, provider, speech_input_engine, _ = make_coordinator(
        speech_inputs=[
            "First message.",
            "Second message.",
            "Third message.",
        ],
        session=session,
        response_text="Turn response.",
        speech_engine=speech_engine,
    )

    coordinator.run()

    assert session.state is ConversationState.ENDED
    assert speech_input_engine.calls == 3
    assert len(provider.messages) == 3
    assert [message.content for message in provider.messages] == [
        "First message.",
        "Second message.",
        "Third message.",
    ]
    assert len(speech_engine.requests) == 3


def test_speak_response_sends_request_to_speech_engine():
    coordinator, _, _, speech_engine = make_coordinator(
        response_text="Spoken response.",
    )

    response = coordinator.process_text_turn("Please respond.")
    coordinator.speak_response(response)

    assert len(speech_engine.requests) == 1

    request = speech_engine.requests[0]

    assert request.text == "Spoken response."
    assert request.voice == "female"
    assert request.speed == 1.0


def test_speak_response_rejects_invalid_response():
    coordinator, _, _, _ = make_coordinator()

    with pytest.raises(TypeError):
        coordinator.speak_response(object())


def test_capture_voice_input_rejects_invalid_speech_result():
    business = make_business()

    provider = RecordingAIProvider()

    processor = AssistantProcessor(
        ai_provider=provider,
        validator=AIInterpretationValidator(),
    )

    orchestrator = AssistantOrchestrator(
        business=business,
        processor=processor,
        executor=make_action_executor(),
    )

    coordinator = AssistantConversationCoordinator(
        business=business,
        orchestrator=orchestrator,
        speech_input_engine=InvalidSpeechInputEngine(),
        speech_engine=RecordingSpeechEngine(),
        voice_service=VoiceService(),
        voice_configuration=VoiceConfiguration(
            voice="female",
            speed=1.0,
        ),
        message_adapter=ConversationMessageAdapter(),
    )

    with pytest.raises(TypeError):
        coordinator.capture_voice_input()


def test_ended_session_cannot_restart():
    session = ConversationSession()

    session.start_listening()
    session.stop()

    coordinator, _, _, _ = make_coordinator(
        session=session,
    )

    assert coordinator.session.state is ConversationState.ENDED

    with pytest.raises(RuntimeError):
        coordinator.run()


def test_processing_failure_moves_session_to_error():
    class FailingAIProvider(AIProvider):
        def interpret(self, message):
            raise RuntimeError("AI processing failed.")

    business = make_business()

    processor = AssistantProcessor(
        ai_provider=FailingAIProvider(),
        validator=AIInterpretationValidator(),
    )

    orchestrator = AssistantOrchestrator(
        business=business,
        processor=processor,
        executor=make_action_executor(),
    )

    speech_input_engine = RecordingSpeechInputEngine(
        ["Hello assistant."],
    )

    coordinator = AssistantConversationCoordinator(
        business=business,
        orchestrator=orchestrator,
        speech_input_engine=speech_input_engine,
        speech_engine=RecordingSpeechEngine(),
        voice_service=VoiceService(),
        voice_configuration=VoiceConfiguration(
            voice="female",
            speed=1.0,
        ),
        message_adapter=ConversationMessageAdapter(),
    )

    with pytest.raises(
        RuntimeError,
        match="AI processing failed.",
    ):
        coordinator.run()

    assert coordinator.session.state is ConversationState.ERROR


def test_process_input_does_not_change_session_state():
    coordinator, _, _, _ = make_coordinator()

    conversation_input = ConversationInput(
        text="Hello.",
        source=ConversationInputSource.TEXT,
    )

    coordinator.process_input(conversation_input)

    assert coordinator.session.state is ConversationState.IDLE


def test_run_preserves_state_after_successful_turn():
    session = ConversationSession()

    speech_engine = StopAfterTurnsSpeechEngine(
        session=session,
        stop_after=1,
    )

    coordinator, provider, speech_input_engine, _ = make_coordinator(
        speech_inputs=["Hello assistant."],
        session=session,
        response_text="Hello from Configured Test Assistant.",
        speech_engine=speech_engine,
    )

    coordinator.run()

    assert provider.messages[0].content == "Hello assistant."
    assert speech_engine.requests[0].text == "Hello from Configured Test Assistant."
    assert speech_input_engine.calls == 1
    assert coordinator.session.state is ConversationState.ENDED
