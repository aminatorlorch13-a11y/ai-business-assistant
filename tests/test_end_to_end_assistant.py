from app.ai.deterministic_raw_provider import DeterministicRawAIProvider
from app.ai.interpreting_provider import InterpretingAIProvider
from app.ai.rule_based_provider import RuleBasedAIProvider
from app.assistant.action_executor import ActionExecutor
from app.assistant.interpretation_validator import AIInterpretationValidator
from app.assistant.orchestrator import AssistantOrchestrator
from app.assistant.processor import AssistantProcessor
from app.assistant.message import AssistantMessage
from app.models.business import Business
from app.services.appointment_operation import AppointmentOperation
from app.trust.action_policy import ActionPolicy


def make_business() -> Business:
    return Business(
        business_id="business-001",
        name="Business One",
        owner_name="Owner One",
        assistant_name="Business Assistant",
        assistant_voice="female",
    )


def test_assistant_handles_create_appointment_end_to_end():
    provider = RuleBasedAIProvider()

    processor = AssistantProcessor(
        ai_provider=provider,
        validator=AIInterpretationValidator(),
    )

    operation = AppointmentOperation()
    policy = ActionPolicy()

    executor = ActionExecutor(
        policy=policy,
        operation=operation,
    )

    orchestrator = AssistantOrchestrator(
        business=make_business(),
        processor=processor,
        executor=executor,
    )

    message = AssistantMessage(
        business_id="business-001",
        content="Please create an appointment.",
    )

    response = orchestrator.handle(message, confirmed=True)

    assert response.business_id == "business-001"
    assert response.assistant_name == "Business Assistant"
    assert response.message == "Appointment creation requested."
    assert response.should_speak is True



def test_assistant_handles_create_appointment_with_interpreting_ai_provider():
    provider = InterpretingAIProvider(
        raw_provider=DeterministicRawAIProvider(),
    )

    processor = AssistantProcessor(
        ai_provider=provider,
        validator=AIInterpretationValidator(),
    )

    operation = AppointmentOperation()
    policy = ActionPolicy()

    executor = ActionExecutor(
        policy=policy,
        operation=operation,
    )

    orchestrator = AssistantOrchestrator(
        business=make_business(),
        processor=processor,
        executor=executor,
    )

    message = AssistantMessage(
        business_id="business-001",
        content="Please create an appointment.",
    )

    response = orchestrator.handle(message, confirmed=True)

    assert response.business_id == "business-001"
    assert response.assistant_name == "Business Assistant"
    assert response.message == "Appointment creation requested."
    assert response.should_speak is True
