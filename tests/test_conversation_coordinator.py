from unittest.mock import Mock
from datetime import datetime, timezone

import pytest

from app.assistant.conversation import (
    ConversationHistory,
    ConversationRole,
    ConversationTurn,
)
from app.assistant.intent import AssistantIntent
from app.assistant.orchestrator import AssistantOrchestrator
from app.assistant.response import AssistantResponse
from app.memory.context import MemoryContext
from app.memory.context import MemoryContextBuilder
from app.models.business import Business
from app.models.voice import VoiceConfiguration
from app.voice.conversation import ConversationState
from app.voice.conversation_coordinator import (
    AssistantConversationCoordinator as _ProductionAssistantConversationCoordinator,
)
from tests.test_safety_helpers import AllowAllTestSafetyEnforcement
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
from app.ai.structured_provider import StructuredAIProvider
from app.assistant.ai_result import AIResult
from app.assistant.ai_capability_request import AICapabilityRequest
from app.assistant.capability import Capability
from app.assistant.capability_confirmation_service import CapabilityConfirmationService
from app.assistant.capability_preparation import CapabilityExecutionPreparer
from app.assistant.structured_processor import StructuredAssistantProcessor
from app.commercial.access import BusinessAccessService
from app.persistence.capability_confirmation import SQLiteCapabilityConfirmationRepository
from app.persistence.database import SQLiteDatabase
from app.trust.capability_executor import CapabilityExecutor
from app.trust.capability_operation_policy import CapabilityOperationPolicy
from pathlib import Path
from tempfile import TemporaryDirectory











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




def make_coordinator(
    *,
    speech_inputs=None,
    session=None,
    response_text="AI response",
    speech_engine=None,
):
    business = make_business()

    provider = RecordingStructuredAIProvider(
        response_text=response_text,
    )

    processor = make_structured_processor(
        provider,
        business.business_id,
    )

    runtime = make_runtime_dependencies(business.business_id)

    orchestrator, confirmation_directory = make_structured_orchestrator(
        business,
        processor,
        commercial_access=runtime.commercial_access,
    )

    speech_input_engine = RecordingSpeechInputEngine(
        speech_inputs or ["Hello assistant."]
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
        commercial_access=runtime.commercial_access,
        tenant=runtime.tenant,
    )

    # Keep the temporary SQLite resources alive for the coordinator lifetime.
    coordinator._test_runtime_dependencies = runtime
    coordinator._test_confirmation_directory = confirmation_directory

    return (
        coordinator,
        provider,
        speech_input_engine,
        speech_engine,
    )


class RecordingStructuredAIProvider(StructuredAIProvider):
    def __init__(self, response_text="AI response", capability_requests=()):
        self.response_text = response_text
        self.capability_requests = tuple(capability_requests)
        self.messages = []
        self.contexts = []

    def generate(self, message, context):
        self.messages.append(message)
        self.contexts.append(context)
        return AIResult(
            response=self.response_text,
            capability_requests=self.capability_requests,
        )


class FailingStructuredAIProvider(StructuredAIProvider):
    def __init__(self, error="AI processing failed."):
        self.error = error
        self.messages = []
        self.contexts = []

    def generate(self, message, context):
        self.messages.append(message)
        self.contexts.append(context)
        raise RuntimeError(self.error)


def make_structured_processor(provider, business_id):
    memory_context_builder = Mock(spec=MemoryContextBuilder)
    memory_context_builder.build.return_value = MemoryContext(
        business_id=business_id,
        memories=(),
    )
    return StructuredAssistantProcessor(
        ai_provider=provider,
        memory_context_builder=memory_context_builder,
    )


def make_structured_confirmation_service(
    business_id: str,
    user_id: str = "runtime-test-user",
):
    temporary_directory = TemporaryDirectory(
        prefix="ai-business-assistant-confirmation-test-"
    )
    database = SQLiteDatabase(
        Path(temporary_directory.name) / "confirmation.sqlite3"
    )
    database.initialize()

    # Seed the parent records required by confirmation foreign keys.
    with database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO businesses(
                business_id, name, owner_name, assistant_name, assistant_voice
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                business_id,
                "Confirmation Test Business",
                "Confirmation Test Owner",
                "Confirmation Test Assistant",
                "female",
            ),
        )
        connection.execute(
            """
            INSERT INTO users(user_id, display_name, email)
            VALUES (?, ?, ?)
            """,
            (
                user_id,
                "Confirmation Test User",
                f"{user_id}@example.test",
            ),
        )

    service = CapabilityConfirmationService(
        SQLiteCapabilityConfirmationRepository(database),
        clock=lambda: datetime.now(timezone.utc),
    )
    return service, temporary_directory


def make_structured_orchestrator(
    business,
    processor,
    executor=None,
    commercial_access=None,
):
    if executor is None:
        executor = Mock(spec=CapabilityExecutor)

    if commercial_access is None:
        runtime = make_runtime_dependencies(business.business_id)
        commercial_access = runtime.commercial_access

    operation_policy = CapabilityOperationPolicy(
        confirmation_by_operation={
            Capability.MEMORY: {
                "save": False,
                "get": False,
                "list": False,
                "delete": True,
            }
        }
    )

    confirmation_service, confirmation_directory = (
        make_structured_confirmation_service(business.business_id)
    )

    orchestrator = AssistantOrchestrator(
        business=business,
        processor=processor,
        executor=executor,
        capability_operation_policy=operation_policy,
        capability_preparer=CapabilityExecutionPreparer(),
        confirmation_service=confirmation_service,
        commercial_access=commercial_access,
    )

    return orchestrator, confirmation_directory


def make_structured_save_request():
    return AICapabilityRequest(
        capability=Capability.MEMORY,
        operation="save",
        arguments={
            "memory_id": "memory-001",
            "content": "Coordinator test memory.",
            "memory_type": "test",
            "importance": 5,
        },
        reason="Coordinator execution test.",
        reversible=True,
    )
def test_coordinator_rejects_foreign_business_conversation_history():
    session = ConversationSession()
    session.history = ConversationHistory(
        business_id="business-foreign",
        turns=(
            ConversationTurn(
                business_id="business-foreign",
                role=ConversationRole.USER,
                content="This belongs to another business.",
            ),
        ),
    )

    with pytest.raises(
        ValueError,
        match="Conversation session history does not belong to this business.",
    ):
        make_coordinator(session=session)


def test_session_rejects_foreign_business_turn_at_runtime():
    session = ConversationSession()

    session.record_turn(
        business_id="business-123",
        role=ConversationRole.USER,
        content="Business A conversation.",
    )

    with pytest.raises(
        ValueError,
        match="Conversation history does not belong to this business.",
    ):
        session.record_turn(
            business_id="business-foreign",
            role=ConversationRole.USER,
            content="Business B must never enter Business A history.",
        )

    assert session.history is not None
    assert session.history.business_id == "business-123"
    assert len(session.history.turns) == 1
    assert session.history.turns[0].business_id == "business-123"
    assert session.history.turns[0].content == "Business A conversation."


def test_failed_interpretation_does_not_record_conversation_history():
    coordinator, provider, _, _ = make_coordinator()

    original_handle = coordinator._orchestrator.handle

    def failing_handle(*args, **kwargs):
        raise RuntimeError("AI interpretation failed.")

    coordinator._orchestrator.handle = failing_handle

    with pytest.raises(RuntimeError, match="AI interpretation failed."):
        coordinator.process_text_turn("This must not become completed history.")

    history = coordinator.session.history

    assert history is not None
    assert history.business_id == "business-123"
    assert history.is_empty is True

    # Restore the real handler so this test cannot leave a mutated
    # coordinator object in an unexpected state if execution changes later.
    coordinator._orchestrator.handle = original_handle


def test_failed_execution_does_not_record_conversation_history():
    business = make_business()
    provider = RecordingStructuredAIProvider(
        response_text=None,
        capability_requests=(make_structured_save_request(),),
    )
    processor = make_structured_processor(
        provider,
        business.business_id,
    )
    runtime = make_runtime_dependencies(business.business_id)

    executor = Mock(spec=CapabilityExecutor)
    executor.execute.side_effect = RuntimeError(
        "Business execution failed."
    )

    orchestrator, confirmation_directory = make_structured_orchestrator(
        business,
        processor,
        executor=executor,
        commercial_access=runtime.commercial_access,
    )

    coordinator = AssistantConversationCoordinator(
        business=business,
        orchestrator=orchestrator,
        speech_input_engine=RecordingSpeechInputEngine(
            ["Remember that this action must not become completed history."]
        ),
        speech_engine=RecordingSpeechEngine(),
        voice_service=VoiceService(),
        voice_configuration=VoiceConfiguration(
            voice="female",
            speed=1.0,
        ),
        message_adapter=ConversationMessageAdapter(),
        commercial_access=runtime.commercial_access,
        tenant=runtime.tenant,
    )

    # The initial request should produce a confirmation, not execute the save.
    response = coordinator.process_text_turn(
        "Remember that this action must not become completed history."
    )
    marker = "Confirmation ID: "
    assert marker in response.message
    confirmation_id = response.message.split(marker, 1)[1].strip()
    assert confirmation_id

    history = coordinator.session.history
    assert history is not None
    assert history.business_id == business.business_id

    # The request and confirmation response are legitimate completed turns.
    recorded_turn_count = len(history.turns)
    assert recorded_turn_count == 2
    executor.execute.assert_not_called()

    # A failed confirmed execution must not append a false assistant result.
    with pytest.raises(
        RuntimeError,
        match="Business execution failed.",
    ):
        coordinator.process_confirmation(confirmation_id)

    history_after_failure = coordinator.session.history
    assert history_after_failure is not None
    assert len(history_after_failure.turns) == recorded_turn_count
    executor.execute.assert_called_once()

def test_speech_failure_preserves_completed_conversation_history():
    class FailingSpeechEngine(RecordingSpeechEngine):
        def speak(self, request):
            super().speak(request)
            raise RuntimeError("Speech synthesis failed.")

    speech_engine = FailingSpeechEngine()

    coordinator, provider, _, _ = make_coordinator(
        response_text="The business request was successfully completed.",
        speech_engine=speech_engine,
    )

    response = coordinator.process_text_turn(
        "Complete this business request."
    )

    assert response.message == (
        "The business request was successfully completed."
    )

    with pytest.raises(
        RuntimeError,
        match="Speech synthesis failed.",
    ):
        coordinator.speak_response(response)

    history = coordinator.session.history

    assert history is not None
    assert history.business_id == "business-123"
    assert len(history.turns) == 2

    assert history.turns[0].role == ConversationRole.USER
    assert history.turns[0].content == (
        "Complete this business request."
    )

    assert history.turns[1].role == ConversationRole.ASSISTANT
    assert history.turns[1].content == (
        "The business request was successfully completed."
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


def test_coordinator_retains_long_conversation_history():
    business = make_business()

    provider = RecordingStructuredAIProvider(
        response_text="Acknowledged."
    )

    processor = make_structured_processor(
        provider,
        business.business_id,
    )

    runtime = make_runtime_dependencies(business.business_id)

    orchestrator, confirmation_directory = make_structured_orchestrator(
        business,
        processor,
        commercial_access=runtime.commercial_access,
    )

    session = ConversationSession()

    coordinator = AssistantConversationCoordinator(
        business=business,
        orchestrator=orchestrator,
        speech_input_engine=RecordingSpeechInputEngine([]),
        speech_engine=RecordingSpeechEngine(),
        voice_service=VoiceService(),
        voice_configuration=VoiceConfiguration(
            voice="female",
            speed=1.0,
        ),
        message_adapter=ConversationMessageAdapter(),
        session=session,
        commercial_access=runtime.commercial_access,
        tenant=runtime.tenant,
    )

    for number in range(1, 31):
        coordinator.process_text_turn(
            f"Conversation message {number}."
        )

    assert len(provider.messages) == 30
    assert len(provider.contexts) == 30

    final_history = provider.contexts[-1].conversation_history

    # The provider receives completed prior exchanges, excluding the
    # current message until the Assistant Core successfully responds.
    assert final_history.business_id == business.business_id
    assert final_history.max_turns is None
    assert len(final_history.turns) == 58

    expected_prior_contents = []
    for number in range(1, 30):
        expected_prior_contents.append(f"Conversation message {number}.")
        expected_prior_contents.append("Acknowledged.")

    assert [turn.content for turn in final_history.turns] == expected_prior_contents
    assert all(
        turn.business_id == business.business_id
        for turn in final_history.turns
    )
    assert final_history.turns[0].role == ConversationRole.USER
    assert final_history.turns[-1].role == ConversationRole.ASSISTANT

    # The session itself must retain all 30 completed exchanges.
    complete_history = session.history
    assert complete_history is not None
    assert complete_history.business_id == business.business_id
    assert complete_history.max_turns is None
    assert len(complete_history.turns) == 60

    expected_complete_contents = []
    for number in range(1, 31):
        expected_complete_contents.append(f"Conversation message {number}.")
        expected_complete_contents.append("Acknowledged.")

    assert [turn.content for turn in complete_history.turns] == expected_complete_contents
    assert all(
        turn.business_id == business.business_id
        for turn in complete_history.turns
    )
    assert complete_history.turns[0].role == ConversationRole.USER
    assert complete_history.turns[-1].role == ConversationRole.ASSISTANT


def test_new_conversation_session_starts_with_empty_history():
    business = make_business()

    provider = RecordingStructuredAIProvider(
        response_text="Acknowledged."
    )

    processor = make_structured_processor(
        provider,
        business.business_id,
    )

    runtime = make_runtime_dependencies(business.business_id)

    orchestrator, confirmation_directory = make_structured_orchestrator(
        business,
        processor,
        commercial_access=runtime.commercial_access,
    )

    first_session = ConversationSession()

    first_coordinator = AssistantConversationCoordinator(
        business=business,
        orchestrator=orchestrator,
        speech_input_engine=RecordingSpeechInputEngine([]),
        speech_engine=RecordingSpeechEngine(),
        voice_service=VoiceService(),
        voice_configuration=VoiceConfiguration(
            voice="female",
            speed=1.0,
        ),
        message_adapter=ConversationMessageAdapter(),
        session=first_session,
        commercial_access=runtime.commercial_access,
        tenant=runtime.tenant,
    )

    first_coordinator.process_text_turn(
        "This belongs to the first conversation."
    )

    assert len(provider.contexts) == 1
    assert provider.contexts[0].conversation_history.is_empty is True

    second_session = ConversationSession()

    second_coordinator = AssistantConversationCoordinator(
        business=business,
        orchestrator=orchestrator,
        speech_input_engine=RecordingSpeechInputEngine([]),
        speech_engine=RecordingSpeechEngine(),
        voice_service=VoiceService(),
        voice_configuration=VoiceConfiguration(
            voice="female",
            speed=1.0,
        ),
        message_adapter=ConversationMessageAdapter(),
        session=second_session,
        commercial_access=runtime.commercial_access,
        tenant=runtime.tenant,
    )

    second_coordinator.process_text_turn(
        "This belongs to the second conversation."
    )

    assert len(provider.contexts) == 2

    second_history = provider.contexts[1].conversation_history

    assert second_history.business_id == business.business_id
    assert second_history.is_empty is True

    assert second_session.history is not None
    assert second_session.history.business_id == business.business_id
    assert second_session.history.is_empty is False

    assert first_session.history is not None
    assert first_session.history.business_id == business.business_id
    assert first_session.history.is_empty is False


def test_ended_conversation_rejects_direct_input_processing():
    business = make_business()

    provider = RecordingStructuredAIProvider(
        response_text="Acknowledged."
    )

    processor = make_structured_processor(
        provider,
        business.business_id,
    )

    runtime = make_runtime_dependencies(business.business_id)

    orchestrator, confirmation_directory = make_structured_orchestrator(
        business,
        processor,
        commercial_access=runtime.commercial_access,
    )

    session = ConversationSession()

    coordinator = AssistantConversationCoordinator(
        business=business,
        orchestrator=orchestrator,
        speech_input_engine=RecordingSpeechInputEngine([]),
        speech_engine=RecordingSpeechEngine(),
        voice_service=VoiceService(),
        voice_configuration=VoiceConfiguration(
            voice="female",
            speed=1.0,
        ),
        message_adapter=ConversationMessageAdapter(),
        session=session,
        commercial_access=runtime.commercial_access,
        tenant=runtime.tenant,
    )

    coordinator.process_text_turn(
        "This turn completes before the session ends."
    )

    assert session.history is not None
    assert len(session.history.turns) == 2

    session.stop()

    assert session.state is ConversationState.ENDED

    with pytest.raises(RuntimeError, match="ended"):
        coordinator.process_text_turn(
            "This must never reach the Assistant Core."
        )

    assert len(provider.messages) == 1
    assert len(provider.contexts) == 1


def test_ended_conversation_rejects_voice_input_processing():
    business = make_business()

    provider = RecordingStructuredAIProvider(
        response_text="Acknowledged."
    )

    processor = make_structured_processor(
        provider,
        business.business_id,
    )

    runtime = make_runtime_dependencies(business.business_id)

    orchestrator, confirmation_directory = make_structured_orchestrator(
        business,
        processor,
        commercial_access=runtime.commercial_access,
    )

    session = ConversationSession()

    coordinator = AssistantConversationCoordinator(
        business=business,
        orchestrator=orchestrator,
        speech_input_engine=RecordingSpeechInputEngine([]),
        speech_engine=RecordingSpeechEngine(),
        voice_service=VoiceService(),
        voice_configuration=VoiceConfiguration(
            voice="female",
            speed=1.0,
        ),
        message_adapter=ConversationMessageAdapter(),
        session=session,
        commercial_access=runtime.commercial_access,
        tenant=runtime.tenant,
    )

    coordinator.process_text_turn(
        "Complete the first conversation turn."
    )

    session.stop()

    assert session.state is ConversationState.ENDED

    voice_input = ConversationInput(
        text="This voice turn must never execute.",
        source=ConversationInputSource.VOICE,
    )

    with pytest.raises(RuntimeError, match="ended"):
        coordinator.process_input(voice_input)

    assert len(provider.messages) == 1
    assert len(provider.contexts) == 1


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
    runtime = make_runtime_dependencies(business.business_id)

    provider = RecordingStructuredAIProvider()

    processor = make_structured_processor(
        provider,
        business.business_id,
    )

    orchestrator, confirmation_directory = make_structured_orchestrator(
        business,
        processor,
        commercial_access=runtime.commercial_access,
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
        commercial_access=runtime.commercial_access,
        tenant=runtime.tenant,
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
    business = make_business()
    runtime = make_runtime_dependencies(business.business_id)

    provider = FailingStructuredAIProvider(
        error="AI processing failed."
    )

    processor = make_structured_processor(
        provider,
        business.business_id,
    )

    orchestrator, confirmation_directory = make_structured_orchestrator(
        business,
        processor,
        commercial_access=runtime.commercial_access,
    )

    coordinator = AssistantConversationCoordinator(
        business=business,
        orchestrator=orchestrator,
        speech_input_engine=RecordingSpeechInputEngine(
            ["Hello assistant."]
        ),
        speech_engine=RecordingSpeechEngine(),
        voice_service=VoiceService(),
        voice_configuration=VoiceConfiguration(
            voice="female",
            speed=1.0,
        ),
        message_adapter=ConversationMessageAdapter(),
        commercial_access=runtime.commercial_access,
        tenant=runtime.tenant,
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

def test_same_conversation_exposes_prior_turns_to_assistant_core():
    business = make_business()

    provider = RecordingStructuredAIProvider()

    processor = make_structured_processor(
        provider,
        business.business_id,
    )

    runtime = make_runtime_dependencies(business.business_id)

    orchestrator, confirmation_directory = make_structured_orchestrator(
        business,
        processor,
        commercial_access=runtime.commercial_access,
    )

    session = ConversationSession()

    coordinator = AssistantConversationCoordinator(
        business=business,
        orchestrator=orchestrator,
        speech_input_engine=RecordingSpeechInputEngine([]),
        speech_engine=RecordingSpeechEngine(),
        voice_service=VoiceService(),
        voice_configuration=VoiceConfiguration(
            voice="female",
            speed=1.0,
        ),
        message_adapter=ConversationMessageAdapter(),
        session=session,
        commercial_access=runtime.commercial_access,
        tenant=runtime.tenant,
    )

    coordinator.process_text_turn(
        "Research the VAT registration requirements."
    )

    coordinator.process_text_turn(
        "Now summarize what you found."
    )

    assert len(provider.contexts) == 2

    first_context = provider.contexts[0]
    second_context = provider.contexts[1]

    assert first_context.conversation_history.is_empty is True

    history = second_context.conversation_history

    assert history.business_id == business.business_id
    assert len(history.turns) == 2

    assert history.turns[0].business_id == business.business_id
    assert history.turns[0].role.value == "user"
    assert history.turns[0].content == (
        "Research the VAT registration requirements."
    )

    assert history.turns[1].business_id == business.business_id
    assert history.turns[1].role.value == "assistant"
    assert history.turns[1].content == "AI response"

    assert provider.messages[1].content == (
        "Now summarize what you found."
    )
