from __future__ import annotations

from pathlib import Path

import pytest

from app.ai.structured_provider import StructuredAIProvider
from app.assistant.ai_capability_request import AICapabilityRequest
from app.assistant.ai_result import AIResult
from app.assistant.capability_composition import (
    build_production_capability_composition,
)
from app.assistant.capability_preparation import CapabilityExecutionPreparer
from app.assistant.orchestrator import AssistantOrchestrator
from app.assistant.structured_processor import StructuredAssistantProcessor
from app.application.runtime import AssistantRuntime
from app.application.runtime_factory import AssistantRuntimeFactory
from app.assistant.conversation import ConversationRole
from app.assistant.message import AssistantMessage
from app.identity.models import (
    AuthenticatedPrincipal,
    UserRole,
)
from app.identity.tenant import TenantContext
from app.memory.context import MemoryContextBuilder
from app.models.business import Business
from app.models.voice import VoiceConfiguration
from app.persistence.business_repository import SQLiteBusinessRepository
from app.persistence.capability_confirmation import (
    SQLiteCapabilityConfirmationRepository,
)
from app.persistence.capability_confirmation import (
    SQLiteCapabilityConfirmationRepository,
)
from app.persistence.commercial_state_repository import (
    SQLiteCommercialStateRepository,
)
from app.persistence.database import SQLiteDatabase
from app.persistence.capability_confirmation import (
    SQLiteCapabilityConfirmationRepository,
)
from app.persistence.capability_confirmation import (
    SQLiteCapabilityConfirmationRepository,
)
from app.commercial.access import BusinessAccessService
from app.commercial.state import (
    BusinessCommercialState,
    CommercialStatus,
)
from app.assistant.capability_confirmation_service import (
    CapabilityConfirmationService,
)
from app.persistence.capability_entitlement_repository import (
    SQLiteCapabilityEntitlementRepository,
)
from app.assistant.capability import Capability
from app.voice.conversation_coordinator import (
    AssistantConversationCoordinator,
)
from app.voice.message_adapter import ConversationMessageAdapter
from app.voice.session import ConversationSession
from app.voice.speech_input import SpeechInput
from app.voice.input_engine import SpeechInputEngine
from app.voice.engine import SpeechEngine
from app.voice.request import SpeechRequest
from app.voice.service import VoiceService


class RecordingStructuredProvider(StructuredAIProvider):
    def __init__(self, response: str = "Hello from Configured Test Assistant."):
        self.messages: list[AssistantMessage] = []
        self.response = response

    def generate(self, message, context):
        self.messages.append(message)
        return AIResult(response=self.response)


class RecordingSpeechInputEngine(SpeechInputEngine):
    def __init__(self, text: str = "voice input"):
        self.text = text

    def listen(self):
        return SpeechInput(text=self.text)


class RecordingSpeechEngine(SpeechEngine):
    def __init__(self):
        self.requests: list[SpeechRequest] = []

    def speak(self, request):
        self.requests.append(request)

    def cancel_current(self):
        return None


class StopAfterTurnsSpeechEngine(RecordingSpeechEngine):
    def __init__(self, session, stop_after: int):
        super().__init__()
        self._session = session
        self._stop_after = stop_after

    def speak(self, request):
        super().speak(request)
        if len(self.requests) >= self._stop_after:
            self._session.stop()


class InvalidSpeechInputEngine(SpeechInputEngine):
    def listen(self):
        return object()


class RecordingVoiceService(VoiceService):
    def __init__(self):
        pass


def _configure_memory_entitlement(database: SQLiteDatabase, business_id: str):
    with database.connection() as connection:
        connection.execute(
            """
            INSERT INTO business_capability_entitlements
                (business_id, configured_at)
            VALUES (?, CURRENT_TIMESTAMP)
            ON CONFLICT(business_id) DO NOTHING
            """,
            (business_id,),
        )
        connection.execute(
            """
            INSERT INTO business_capability_grants
                (business_id, capability)
            VALUES (?, ?)
            ON CONFLICT(business_id, capability) DO NOTHING
            """,
            (business_id, Capability.MEMORY.value),
        )


def _make_business(business_id: str) -> Business:
    return Business(
        business_id=business_id,
        name="Runtime Test Business",
        owner_name="Runtime Test Owner",
        assistant_name="Runtime Assistant",
        assistant_voice="male",
    )


def _make_stack(
    tmp_path: Path,
    *,
    business_id: str = "runtime-business",
    voice: str = "male",
):
    database = SQLiteDatabase(tmp_path / "runtime.sqlite3")
    database.initialize()

    business = _make_business(business_id)
    SQLiteBusinessRepository(database).save(business)

    SQLiteCommercialStateRepository(database).save(
        BusinessCommercialState(
            business_id=business_id,
            status=CommercialStatus.ACTIVE,
        )
    )

    _configure_memory_entitlement(database, business_id)

    principal = AuthenticatedPrincipal(
        user_id="runtime-test-user",
        business_id=business_id,
        role=UserRole.OWNER,
        session_id="runtime-test-session",
    )
    tenant = TenantContext(
        business_id=business_id,
        principal=principal,
    )

    provider = RecordingStructuredProvider()
    composition = build_production_capability_composition(
        database=database,
    )
    processor = StructuredAssistantProcessor(
        ai_provider=provider,
        memory_context_builder=MemoryContextBuilder(
            composition.memory_service,
        ),
    )

    confirmation_repository = SQLiteCapabilityConfirmationRepository(
        database,
    )
    confirmation_service = CapabilityConfirmationService(
        confirmation_repository,
    )

    commercial_access = BusinessAccessService(database)
    executor = composition.executor_for_business(business_id)

    orchestrator = AssistantOrchestrator(
        business=business,
        processor=processor,
        executor=executor,
        capability_operation_policy=composition.operation_policy,
        capability_preparer=CapabilityExecutionPreparer(),
        confirmation_service=confirmation_service,
        commercial_access=commercial_access,
    )

    session = ConversationSession()

    coordinator = AssistantConversationCoordinator(
        business=business,
        orchestrator=orchestrator,
        speech_input_engine=RecordingSpeechInputEngine(),
        speech_engine=RecordingSpeechEngine(),
        voice_service=RecordingVoiceService(),
        voice_configuration=VoiceConfiguration(voice=voice),
        message_adapter=ConversationMessageAdapter(),
        commercial_access=commercial_access,
        tenant=tenant,
        session=session,
    )

    runtime = AssistantRuntime(
        business=business,
        orchestrator=orchestrator,
        conversation_coordinator=coordinator,
    )

    return {
        "database": database,
        "business": business,
        "tenant": tenant,
        "provider": provider,
        "orchestrator": orchestrator,
        "coordinator": coordinator,
        "runtime": runtime,
        "session": session,
        "commercial_access": commercial_access,
    }


def test_runtime_factory_returns_runtime(tmp_path):
    stack = _make_stack(tmp_path)

    runtime = AssistantRuntimeFactory.create(
        business=stack["business"],
        orchestrator=stack["orchestrator"],
        speech_input_engine=RecordingSpeechInputEngine(),
        speech_engine=RecordingSpeechEngine(),
        voice_service=RecordingVoiceService(),
        voice_configuration=VoiceConfiguration(voice="male"),
        message_adapter=ConversationMessageAdapter(),
        commercial_access=stack["commercial_access"],
        tenant=stack["tenant"],
    )

    assert isinstance(runtime, AssistantRuntime)
    assert runtime.business.business_id == stack["business"].business_id


def test_runtime_exposes_business_scoped_session(tmp_path):
    stack = _make_stack(tmp_path)

    stack["runtime"].handle_text("business-scoped session")

    assert stack["runtime"].session is stack["session"]
    assert stack["runtime"].session.history is not None
    assert stack["runtime"].session.history.business_id == (
        stack["business"].business_id
    )


def test_runtime_text_enters_normal_assistant_pipeline(tmp_path):
    stack = _make_stack(tmp_path)

    response = stack["runtime"].handle_text("hello")

    assert response.message == "Hello from Configured Test Assistant."
    assert stack["provider"].messages[-1].business_id == "runtime-business"
    assert stack["provider"].messages[-1].content == "hello"


def test_runtime_voice_turn_enters_same_assistant_pipeline(tmp_path):
    stack = _make_stack(tmp_path)

    response = stack["runtime"].handle_voice_turn()

    assert response.message == "Hello from Configured Test Assistant."
    assert stack["provider"].messages[-1].business_id == "runtime-business"


def test_runtime_voice_input_is_marked_as_voice(tmp_path):
    stack = _make_stack(tmp_path)

    response = stack["runtime"].handle_voice_turn()

    assert response.message == "Hello from Configured Test Assistant."
    assert stack["provider"].messages[-1].content == "voice input"
    assert stack["coordinator"].session.history is not None
    assert stack["coordinator"].session.history.business_id == (
        stack["business"].business_id
    )
    assert stack["coordinator"].session.history.turns[0].role is ConversationRole.USER
    assert stack["coordinator"].session.history.turns[0].content == "voice input"


def test_runtime_text_and_voice_share_business_boundary(tmp_path):
    stack = _make_stack(tmp_path)

    stack["runtime"].handle_text("text")
    stack["runtime"].handle_voice_turn()

    assert all(
        message.business_id == stack["business"].business_id
        for message in stack["provider"].messages
    )


def test_runtime_speaks_response_through_voice_boundary(tmp_path):
    stack = _make_stack(tmp_path)

    speech_engine = RecordingSpeechEngine()
    coordinator = AssistantConversationCoordinator(
        business=stack["business"],
        orchestrator=stack["orchestrator"],
        speech_input_engine=RecordingSpeechInputEngine(),
        speech_engine=speech_engine,
        voice_service=RecordingVoiceService(),
        voice_configuration=VoiceConfiguration(voice="female"),
        message_adapter=ConversationMessageAdapter(),
        commercial_access=stack["commercial_access"],
        tenant=stack["tenant"],
        session=stack["session"],
    )
    runtime = AssistantRuntime(
        business=stack["business"],
        orchestrator=stack["orchestrator"],
        conversation_coordinator=coordinator,
    )

    response = runtime.handle_text("hello")
    runtime.speak_response(response)

    assert len(speech_engine.requests) == 1
    assert speech_engine.requests[0].voice == "female"
    assert speech_engine.requests[0].speed == 1.0


def test_runtime_rejects_response_for_different_business(tmp_path):
    stack = _make_stack(tmp_path)

    from app.assistant.response import AssistantResponse

    response = AssistantResponse(
        business_id="other-business",
        assistant_name="OwnerChosenName",
        message="wrong business",
    )

    with pytest.raises(ValueError):
        stack["runtime"].speak_response(response)


def test_runtime_rejects_invalid_response_type(tmp_path):
    stack = _make_stack(tmp_path)

    with pytest.raises(TypeError):
        stack["runtime"].speak_response(object())


def test_runtime_rejects_empty_text(tmp_path):
    stack = _make_stack(tmp_path)

    with pytest.raises(ValueError):
        stack["runtime"].handle_text("")


def test_runtime_rejects_non_string_text(tmp_path):
    stack = _make_stack(tmp_path)

    with pytest.raises(TypeError):
        stack["runtime"].handle_text(None)


def test_runtime_voice_conversation_uses_coordinator(tmp_path):
    stack = _make_stack(tmp_path)

    response = stack["runtime"].handle_voice_turn()

    assert response.message == "Hello from Configured Test Assistant."
    assert stack["session"].history is not None
    assert len(stack["session"].history.turns) == 2
    assert stack["session"].history.turns[0].role is ConversationRole.USER
    assert stack["session"].history.turns[1].role is ConversationRole.ASSISTANT


def test_runtime_can_be_created_with_explicit_dependencies(tmp_path):
    stack = _make_stack(tmp_path)

    assert isinstance(stack["runtime"], AssistantRuntime)
    assert stack["runtime"].business is stack["business"]


def test_runtime_does_not_directly_execute_business_operations(tmp_path):
    stack = _make_stack(tmp_path)

    forbidden = {
        "execute",
        "create_appointment",
        "send_email",
        "run_business_operation",
    }

    assert forbidden.isdisjoint(set(dir(stack["runtime"])))


def test_runtime_voice_turn_does_not_change_session_state(tmp_path):
    stack = _make_stack(tmp_path)

    assert stack["session"].state.value == "idle"

    stack["runtime"].handle_voice_turn()

    assert stack["session"].state.value == "idle"


def test_runtime_preserves_session_identity(tmp_path):
    stack = _make_stack(tmp_path)

    session = stack["session"]

    stack["runtime"].handle_text("hello")
    stack["runtime"].handle_voice_turn()

    assert stack["runtime"].session is session
    assert stack["coordinator"].session is session


def test_runtime_rejects_invalid_voice_input(tmp_path):
    stack = _make_stack(tmp_path)

    coordinator = AssistantConversationCoordinator(
        business=stack["business"],
        orchestrator=stack["orchestrator"],
        speech_input_engine=InvalidSpeechInputEngine(),
        speech_engine=RecordingSpeechEngine(),
        voice_service=RecordingVoiceService(),
        voice_configuration=VoiceConfiguration(voice="male"),
        message_adapter=ConversationMessageAdapter(),
        commercial_access=stack["commercial_access"],
        tenant=stack["tenant"],
        session=stack["session"],
    )
    runtime = AssistantRuntime(
        business=stack["business"],
        orchestrator=stack["orchestrator"],
        conversation_coordinator=coordinator,
    )

    with pytest.raises(TypeError):
        runtime.handle_voice_turn()


def test_runtime_cannot_restart_after_voice_session_ends(tmp_path):
    stack = _make_stack(tmp_path)

    speech_engine = StopAfterTurnsSpeechEngine(
        stack["session"],
        stop_after=1,
    )
    coordinator = AssistantConversationCoordinator(
        business=stack["business"],
        orchestrator=stack["orchestrator"],
        speech_input_engine=RecordingSpeechInputEngine(),
        speech_engine=speech_engine,
        voice_service=RecordingVoiceService(),
        voice_configuration=VoiceConfiguration(voice="male"),
        message_adapter=ConversationMessageAdapter(),
        commercial_access=stack["commercial_access"],
        tenant=stack["tenant"],
        session=stack["session"],
    )
    runtime = AssistantRuntime(
        business=stack["business"],
        orchestrator=stack["orchestrator"],
        conversation_coordinator=coordinator,
    )

    runtime.run_voice_conversation()

    with pytest.raises(RuntimeError):
        runtime.run_voice_conversation()


def test_runtime_voice_and_text_use_same_business_identity(tmp_path):
    stack = _make_stack(tmp_path)

    stack["runtime"].handle_text("text")
    stack["runtime"].handle_voice_turn()

    assert {
        message.business_id
        for message in stack["provider"].messages
    } == {"runtime-business"}


def test_runtime_rejects_mismatched_orchestrator_business(tmp_path):
    stack = _make_stack(tmp_path)
    other = _make_stack(tmp_path / "other", business_id="other-business")

    with pytest.raises(ValueError):
        AssistantRuntime(
            business=stack["business"],
            orchestrator=other["orchestrator"],
            conversation_coordinator=stack["coordinator"],
        )


def test_runtime_rejects_mismatched_coordinator_business(tmp_path):
    stack = _make_stack(tmp_path)
    other = _make_stack(tmp_path / "other", business_id="other-business")

    with pytest.raises(ValueError):
        AssistantRuntime(
            business=stack["business"],
            orchestrator=stack["orchestrator"],
            conversation_coordinator=other["coordinator"],
        )
