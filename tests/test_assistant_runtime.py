from __future__ import annotations

from unittest.mock import Mock

import pytest

from app.ai.context import AIContext
from app.ai.provider import AIProvider
from app.application.runtime import AssistantRuntime
from app.application.runtime_factory import AssistantRuntimeFactory
from app.assistant.action import AssistantAction
from app.assistant.action_executor import ActionExecutor
from app.assistant.intent import AssistantIntent
from app.assistant.interpretation import AIInterpretation
from app.assistant.interpretation_validator import AIInterpretationValidator
from app.assistant.orchestrator import AssistantOrchestrator
from app.assistant.processor import AssistantProcessor
from app.assistant.response import AssistantResponse
from app.memory.context import MemoryContext
from app.memory.context import MemoryContextBuilder
from app.models.business import Business
from app.models.voice import VoiceConfiguration
from app.services.business_operation import BusinessOperation
from app.trust.action_policy import ActionPolicy
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
from app.voice.input import ConversationInputSource
from app.voice.input_engine import SpeechInputEngine
from app.voice.message_adapter import ConversationMessageAdapter
from app.voice.request import SpeechRequest
from app.voice.service import VoiceService
from app.voice.session import ConversationSession
from tests.runtime_support import make_runtime_dependencies
from app.voice.speech_input import SpeechInput


def make_business(
    business_id: str = "business-runtime",
    assistant_voice: str = "female",
) -> Business:
    return Business(
        business_id=business_id,
        name="Runtime Business",
        owner_name="Test Owner",
        assistant_name="Configured Test Assistant",
        assistant_voice=assistant_voice,
    )


class RecordingAIProvider(AIProvider):
    """
    Deterministic AI provider used only by runtime tests.

    The provider returns a production-valid conversational
    interpretation:

        general_question
            -> none
            -> assistant

    No business operation is required for this conversational action.
    """

    def __init__(self) -> None:
        self.messages = []
        self.contexts = []

    def interpret(
        self,
        message: AssistantMessage,
        context: AIContext,
    ) -> AIInterpretation:
        self.messages.append(message)
        self.contexts.append(context)

        intent = AssistantIntent(
            business_id=message.business_id,
            intent_type="general_question",
            instruction="Answer the user's question.",
        )

        action = AssistantAction(
            business_id=message.business_id,
            action_type="none",
            target="assistant",
            instruction="No business action is required.",
        )

        return AIInterpretation(
            intent=intent,
            action=action,
        )


class RecordingBusinessOperation(BusinessOperation):
    """
    Test-only operation for assistant-level conversational actions.

    Production appointment execution is intentionally not used here.
    This double exists because AppointmentOperation owns appointment
    targets, while these runtime tests exercise the assistant target.

    It records the action and returns a deterministic assistant message.
    """

    def __init__(self) -> None:
        self.actions: list[AssistantAction] = []

    def execute(
        self,
        action: AssistantAction,
        tenant: TenantContext | None = None,
    ) -> str:
        if not isinstance(action, AssistantAction):
            raise TypeError(
                "action must be an AssistantAction."
            )

        if action.action_type != "none":
            raise ValueError(
                "RecordingBusinessOperation only accepts none actions."
            )

        if action.target != "assistant":
            raise ValueError(
                "RecordingBusinessOperation requires an assistant target."
            )

        self.actions.append(action)

        return "Hello from Configured Test Assistant."


class RecordingSpeechInputEngine(SpeechInputEngine):
    """Deterministic speech-input test double."""

    def __init__(self, text: str) -> None:
        if not isinstance(text, str):
            raise TypeError("text must be a string.")

        self.text = text
        self.calls = 0

    def listen(self) -> SpeechInput:
        self.calls += 1
        return SpeechInput(text=self.text)


class RecordingSpeechEngine(SpeechEngine):
    """Deterministic speech-output test double."""

    def __init__(self) -> None:
        self.requests: list[SpeechRequest] = []

    def speak(self, request: SpeechRequest) -> None:
        if not isinstance(request, SpeechRequest):
            raise TypeError(
                "request must be a SpeechRequest."
            )

        self.requests.append(request)

    def cancel_current(self) -> None:
        return None


class StopAfterTurnsSpeechEngine(SpeechEngine):
    """
    Test-only speech engine that explicitly ends the session after
    a configured number of speech outputs.

    This gives continuous-conversation tests a deterministic stopping
    condition without introducing an artificial loop limit into
    production code.
    """

    def __init__(
        self,
        session: ConversationSession,
        turns: int = 1,
    ) -> None:
        if not isinstance(session, ConversationSession):
            raise TypeError(
                "session must be a ConversationSession."
            )

        if not isinstance(turns, int) or isinstance(turns, bool):
            raise TypeError(
                "turns must be an integer."
            )

        if turns <= 0:
            raise ValueError(
                "turns must be greater than zero."
            )

        self._session = session
        self._turns = turns
        self.requests: list[SpeechRequest] = []

    def speak(self, request: SpeechRequest) -> None:
        if not isinstance(request, SpeechRequest):
            raise TypeError(
                "request must be a SpeechRequest."
            )

        self.requests.append(request)

        if len(self.requests) >= self._turns:
            self._session.stop()

    def cancel_current(self) -> None:
        return None


class InvalidSpeechInputEngine(SpeechInputEngine):
    """Invalid speech-input test double."""

    def listen(self) -> SpeechInput:
        return object()


def build_orchestrator(
    business: Business,
    provider: AIProvider,
) -> tuple[AssistantOrchestrator, RecordingBusinessOperation]:
    memory_context_builder = Mock(spec=MemoryContextBuilder)
    memory_context_builder.build.return_value = MemoryContext(
        business_id=business.business_id,
        memories=(),
    )

    processor = AssistantProcessor(
        ai_provider=provider,
        validator=AIInterpretationValidator(),
        memory_context_builder=memory_context_builder,
    )

    operation = RecordingBusinessOperation()

    executor = ActionExecutor(
        policy=ActionPolicy(
            allow_create=True,
            allow_update=True,
            allow_delete=False,
        ),
        operation=operation,
        safety_enforcement=AllowAllTestSafetyEnforcement(),
    )

    orchestrator = AssistantOrchestrator(
        business=business,
        processor=processor,
        executor=executor,
    )

    return orchestrator, operation


def make_runtime(
    business: Business | None = None,
    provider: AIProvider | None = None,
    speech_input_engine: SpeechInputEngine | None = None,
    speech_engine: SpeechEngine | None = None,
    session: ConversationSession | None = None,
) -> AssistantRuntime:
    business = business or make_business()
    provider = provider or RecordingAIProvider()

    speech_input_engine = (
        speech_input_engine
        or RecordingSpeechInputEngine("hello")
    )

    speech_engine = speech_engine or RecordingSpeechEngine()
    session = session or ConversationSession()

    orchestrator, _ = build_orchestrator(
        business=business,
        provider=provider,
    )

    runtime_dependencies = make_runtime_dependencies(business.business_id)
    commercial_access = runtime_dependencies.commercial_access
    tenant = runtime_dependencies.tenant

    coordinator = AssistantConversationCoordinator(
        business=business,
        orchestrator=orchestrator,
        speech_input_engine=speech_input_engine,
        speech_engine=speech_engine,
        voice_service=VoiceService(),
        voice_configuration=VoiceConfiguration(
            voice=business.assistant_voice,
        ),
        message_adapter=ConversationMessageAdapter(),
        session=session,
        commercial_access=commercial_access,
        tenant=tenant,
    )

    runtime = AssistantRuntime(
        business=business,
        orchestrator=orchestrator,
        conversation_coordinator=coordinator,
    )

    # Keep the temporary SQLite directory alive for the runtime's lifetime.
    runtime._runtime_test_dependencies = runtime_dependencies

    return runtime


def test_runtime_factory_returns_runtime() -> None:
    business = make_business()
    provider = RecordingAIProvider()

    orchestrator, _ = build_orchestrator(
        business=business,
        provider=provider,
    )

    runtime_dependencies = make_runtime_dependencies(business.business_id)
    commercial_access = runtime_dependencies.commercial_access
    tenant = runtime_dependencies.tenant

    runtime = AssistantRuntimeFactory.create(
        business=business,
        orchestrator=orchestrator,
        speech_input_engine=RecordingSpeechInputEngine(
            "hello"
        ),
        speech_engine=RecordingSpeechEngine(),
        voice_service=VoiceService(),
        voice_configuration=VoiceConfiguration(
            voice=business.assistant_voice,
        ),
        message_adapter=ConversationMessageAdapter(),
        commercial_access=commercial_access,
        tenant=tenant,
    )

    assert isinstance(runtime, AssistantRuntime)
    assert runtime.business is business
    assert runtime.session.state is ConversationState.IDLE


def test_runtime_exposes_business_scoped_session() -> None:
    runtime = make_runtime()

    assert isinstance(
        runtime.session,
        ConversationSession,
    )

    assert runtime.session.state is ConversationState.IDLE


def test_runtime_text_enters_normal_assistant_pipeline() -> None:
    business = make_business()
    provider = RecordingAIProvider()

    orchestrator, operation = build_orchestrator(
        business=business,
        provider=provider,
    )

    coordinator = AssistantConversationCoordinator(
        business=business,
        orchestrator=orchestrator,
        speech_input_engine=RecordingSpeechInputEngine(
            "hello"
        ),
        speech_engine=RecordingSpeechEngine(),
        voice_service=VoiceService(),
        voice_configuration=VoiceConfiguration(
            voice=business.assistant_voice,
        ),
        message_adapter=ConversationMessageAdapter(),
        session=ConversationSession(),
    )

    runtime = AssistantRuntime(
        business=business,
        orchestrator=orchestrator,
        conversation_coordinator=coordinator,
    )

    response = runtime.handle_text("hello")

    assert isinstance(response, AssistantResponse)
    assert response.business_id == business.business_id
    assert response.assistant_name == business.assistant_name
    assert response.message == "Hello from Configured Test Assistant."

    assert len(provider.messages) == 1
    assert provider.messages[0].business_id == business.business_id

    assert len(operation.actions) == 1
    assert operation.actions[0].business_id == business.business_id
    assert operation.actions[0].action_type == "none"
    assert operation.actions[0].target == "assistant"


def test_runtime_voice_turn_enters_same_assistant_pipeline() -> None:
    business = make_business()
    provider = RecordingAIProvider()

    speech_input = RecordingSpeechInputEngine(
        "hello from voice"
    )

    orchestrator, operation = build_orchestrator(
        business=business,
        provider=provider,
    )

    coordinator = AssistantConversationCoordinator(
        business=business,
        orchestrator=orchestrator,
        speech_input_engine=speech_input,
        speech_engine=RecordingSpeechEngine(),
        voice_service=VoiceService(),
        voice_configuration=VoiceConfiguration(
            voice=business.assistant_voice,
        ),
        message_adapter=ConversationMessageAdapter(),
        session=ConversationSession(),
    )

    runtime = AssistantRuntime(
        business=business,
        orchestrator=orchestrator,
        conversation_coordinator=coordinator,
    )

    response = runtime.handle_voice_turn()

    assert isinstance(response, AssistantResponse)
    assert response.business_id == business.business_id
    assert response.message == "Hello from Configured Test Assistant."

    assert speech_input.calls == 1
    assert len(provider.messages) == 1
    assert provider.messages[0].business_id == business.business_id

    assert len(operation.actions) == 1
    assert operation.actions[0].target == "assistant"


def test_runtime_voice_input_is_marked_as_voice() -> None:
    speech_input = RecordingSpeechInputEngine(
        "voice message"
    )

    runtime = make_runtime(
        speech_input_engine=speech_input,
    )

    captured = (
        runtime.conversation_coordinator.capture_voice_input()
    )

    assert (
        captured.source
        is ConversationInputSource.VOICE
    )

    assert captured.text == "voice message"


def test_runtime_text_and_voice_share_business_boundary() -> None:
    business = make_business()
    provider = RecordingAIProvider()
    speech_input = RecordingSpeechInputEngine(
        "voice message"
    )

    orchestrator, operation = build_orchestrator(
        business=business,
        provider=provider,
    )

    coordinator = AssistantConversationCoordinator(
        business=business,
        orchestrator=orchestrator,
        speech_input_engine=speech_input,
        speech_engine=RecordingSpeechEngine(),
        voice_service=VoiceService(),
        voice_configuration=VoiceConfiguration(
            voice=business.assistant_voice,
        ),
        message_adapter=ConversationMessageAdapter(),
        session=ConversationSession(),
    )

    runtime = AssistantRuntime(
        business=business,
        orchestrator=orchestrator,
        conversation_coordinator=coordinator,
    )

    runtime.handle_text("text message")
    runtime.handle_voice_turn()

    assert len(provider.messages) == 2

    assert all(
        message.business_id == business.business_id
        for message in provider.messages
    )

    assert len(operation.actions) == 2

    assert all(
        action.business_id == business.business_id
        for action in operation.actions
    )


def test_runtime_speaks_response_through_voice_boundary() -> None:
    speech_engine = RecordingSpeechEngine()

    runtime = make_runtime(
        speech_engine=speech_engine,
    )

    response = AssistantResponse(
        business_id=runtime.business.business_id,
        assistant_name=runtime.business.assistant_name,
        message="Hello from Configured Test Assistant.",
        should_speak=True,
    )

    runtime.speak_response(response)

    assert len(speech_engine.requests) == 1

    request = speech_engine.requests[0]

    assert request.text == "Hello from Configured Test Assistant."
    assert request.voice == "female"
    assert request.speed == 1.0


def test_runtime_rejects_response_for_different_business() -> None:
    runtime = make_runtime()

    response = AssistantResponse(
        business_id="different-business",
        assistant_name="Configured Test Assistant",
        message="Cross-business response.",
        should_speak=True,
    )

    with pytest.raises(
        ValueError,
        match="does not belong",
    ):
        runtime.speak_response(response)


def test_runtime_rejects_invalid_response_type() -> None:
    runtime = make_runtime()

    with pytest.raises(TypeError):
        runtime.speak_response(object())


def test_runtime_rejects_empty_text() -> None:
    runtime = make_runtime()

    with pytest.raises(ValueError):
        runtime.handle_text("   ")


def test_runtime_rejects_non_string_text() -> None:
    runtime = make_runtime()

    with pytest.raises(TypeError):
        runtime.handle_text(None)


def test_runtime_voice_conversation_uses_coordinator() -> None:
    business = make_business()
    session = ConversationSession()
    provider = RecordingAIProvider()

    speech_input = RecordingSpeechInputEngine(
        "hello"
    )

    speech_engine = StopAfterTurnsSpeechEngine(
        session=session,
        turns=1,
    )

    orchestrator, operation = build_orchestrator(
        business=business,
        provider=provider,
    )

    coordinator = AssistantConversationCoordinator(
        business=business,
        orchestrator=orchestrator,
        speech_input_engine=speech_input,
        speech_engine=speech_engine,
        voice_service=VoiceService(),
        voice_configuration=VoiceConfiguration(
            voice=business.assistant_voice,
        ),
        message_adapter=ConversationMessageAdapter(),
        session=session,
    )

    runtime = AssistantRuntime(
        business=business,
        orchestrator=orchestrator,
        conversation_coordinator=coordinator,
    )

    runtime.run_voice_conversation()

    assert runtime.session.state is ConversationState.ENDED
    assert speech_input.calls == 1
    assert len(speech_engine.requests) == 1
    assert len(provider.messages) == 1
    assert len(operation.actions) == 1


def test_runtime_can_be_created_with_explicit_dependencies() -> None:
    business = make_business()
    provider = RecordingAIProvider()

    speech_input = RecordingSpeechInputEngine(
        "explicit dependency"
    )

    speech_engine = RecordingSpeechEngine()
    session = ConversationSession()

    runtime = make_runtime(
        business=business,
        provider=provider,
        speech_input_engine=speech_input,
        speech_engine=speech_engine,
        session=session,
    )

    assert runtime.business is business
    assert runtime.session is session
    assert (
        runtime.conversation_coordinator.session
        is session
    )


def test_runtime_does_not_directly_execute_business_operations() -> None:
    runtime = make_runtime()

    assert not hasattr(runtime, "execute")
    assert not hasattr(
        runtime,
        "create_appointment",
    )
    assert not hasattr(
        runtime,
        "update_appointment",
    )
    assert not hasattr(
        runtime,
        "delete_appointment",
    )


def test_runtime_voice_turn_does_not_change_session_state() -> None:
    runtime = make_runtime()

    assert runtime.session.state is ConversationState.IDLE

    runtime.handle_voice_turn()

    assert runtime.session.state is ConversationState.IDLE


def test_runtime_preserves_session_identity() -> None:
    session = ConversationSession()

    runtime = make_runtime(
        session=session,
    )

    assert runtime.session is session
    assert (
        runtime.conversation_coordinator.session
        is session
    )


def test_runtime_rejects_invalid_voice_input() -> None:
    runtime = make_runtime(
        speech_input_engine=InvalidSpeechInputEngine(),
    )

    with pytest.raises(TypeError):
        runtime.handle_voice_turn()


def test_runtime_cannot_restart_after_voice_session_ends() -> None:
    business = make_business()
    session = ConversationSession()
    provider = RecordingAIProvider()

    speech_input = RecordingSpeechInputEngine(
        "hello"
    )

    speech_engine = StopAfterTurnsSpeechEngine(
        session=session,
        turns=1,
    )

    orchestrator, operation = build_orchestrator(
        business=business,
        provider=provider,
    )

    coordinator = AssistantConversationCoordinator(
        business=business,
        orchestrator=orchestrator,
        speech_input_engine=speech_input,
        speech_engine=speech_engine,
        voice_service=VoiceService(),
        voice_configuration=VoiceConfiguration(
            voice=business.assistant_voice,
        ),
        message_adapter=ConversationMessageAdapter(),
        session=session,
    )

    runtime = AssistantRuntime(
        business=business,
        orchestrator=orchestrator,
        conversation_coordinator=coordinator,
    )

    runtime.run_voice_conversation()

    assert runtime.session.state is ConversationState.ENDED
    assert len(operation.actions) == 1

    with pytest.raises(RuntimeError):
        runtime.run_voice_conversation()


def test_runtime_voice_and_text_use_same_business_identity() -> None:
    business = make_business()
    provider = RecordingAIProvider()

    speech_input = RecordingSpeechInputEngine(
        "voice"
    )

    orchestrator, operation = build_orchestrator(
        business=business,
        provider=provider,
    )

    coordinator = AssistantConversationCoordinator(
        business=business,
        orchestrator=orchestrator,
        speech_input_engine=speech_input,
        speech_engine=RecordingSpeechEngine(),
        voice_service=VoiceService(),
        voice_configuration=VoiceConfiguration(
            voice=business.assistant_voice,
        ),
        message_adapter=ConversationMessageAdapter(),
        session=ConversationSession(),
    )

    runtime = AssistantRuntime(
        business=business,
        orchestrator=orchestrator,
        conversation_coordinator=coordinator,
    )

    text_response = runtime.handle_text("text")
    voice_response = runtime.handle_voice_turn()

    assert (
        text_response.business_id
        == business.business_id
    )

    assert (
        voice_response.business_id
        == business.business_id
    )

    assert (
        text_response.assistant_name
        == business.assistant_name
    )

    assert (
        voice_response.assistant_name
        == business.assistant_name
    )

    assert len(provider.messages) == 2
    assert len(operation.actions) == 2


def test_runtime_rejects_mismatched_orchestrator_business() -> None:
    business = make_business(
        "business-runtime"
    )

    other_business = make_business(
        "business-other"
    )

    provider = RecordingAIProvider()

    orchestrator, _ = build_orchestrator(
        business=other_business,
        provider=provider,
    )

    session = ConversationSession()

    coordinator = AssistantConversationCoordinator(
        business=business,
        orchestrator=orchestrator,
        speech_input_engine=RecordingSpeechInputEngine(
            "hello"
        ),
        speech_engine=RecordingSpeechEngine(),
        voice_service=VoiceService(),
        voice_configuration=VoiceConfiguration(
            voice=business.assistant_voice,
        ),
        message_adapter=ConversationMessageAdapter(),
        session=session,
    )

    with pytest.raises(ValueError):
        AssistantRuntime(
            business=business,
            orchestrator=orchestrator,
            conversation_coordinator=coordinator,
        )


def test_runtime_rejects_mismatched_coordinator_business() -> None:
    business = make_business(
        "business-runtime"
    )

    other_business = make_business(
        "business-other"
    )

    provider = RecordingAIProvider()

    orchestrator, _ = build_orchestrator(
        business=business,
        provider=provider,
    )

    coordinator = AssistantConversationCoordinator(
        business=other_business,
        orchestrator=orchestrator,
        speech_input_engine=RecordingSpeechInputEngine(
            "hello"
        ),
        speech_engine=RecordingSpeechEngine(),
        voice_service=VoiceService(),
        voice_configuration=VoiceConfiguration(
            voice=other_business.assistant_voice,
        ),
        message_adapter=ConversationMessageAdapter(),
        session=ConversationSession(),
    )

    with pytest.raises(ValueError):
        AssistantRuntime(
            business=business,
            orchestrator=orchestrator,
            conversation_coordinator=coordinator,
        )
