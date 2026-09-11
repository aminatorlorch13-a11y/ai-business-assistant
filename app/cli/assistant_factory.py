from __future__ import annotations

from app.ai.groq_config import GroqConfig
from app.ai.groq_provider import GroqHTTPProvider
from app.ai.interpreting_provider import InterpretingAIProvider
from app.assistant.action_executor import ActionExecutor
from app.assistant.interpretation_validator import AIInterpretationValidator
from app.assistant.orchestrator import AssistantOrchestrator
from app.assistant.processor import AssistantProcessor
from app.models.business import Business
from app.models.voice import SUPPORTED_VOICES
from app.services.appointment_operation import AppointmentOperation
from app.services.assistant_conversation_operation import (
    AssistantConversationOperation,
)
from app.services.target_routed_operation import TargetRoutedOperation
from app.trust.action_policy import ActionPolicy


BUSINESS_ID = "local-business"
BUSINESS_NAME = "My Business"


def build_ai_provider() -> InterpretingAIProvider:
    """
    Construct the production AI provider.

    Raises RuntimeError with a clear message if GROQ_API_KEY is
    missing or misconfigured, rather than failing deep inside a
    request with an opaque error.
    """
    try:
        config = GroqConfig.from_environment()
    except RuntimeError as exc:
        raise RuntimeError(
            "Cannot start assistant: Groq is not configured. "
            f"{exc}"
        ) from exc

    return InterpretingAIProvider(
        raw_provider=GroqHTTPProvider(config)
    )


def build_business_and_orchestrator(
    owner_name: str,
    assistant_name: str,
    assistant_voice: str,
) -> tuple[Business, AssistantOrchestrator]:
    """Build the validated business and its assistant orchestrator."""

    if not owner_name.strip():
        raise ValueError("owner_name must not be empty.")

    if not assistant_name.strip():
        raise ValueError("assistant_name must not be empty.")

    if assistant_voice not in SUPPORTED_VOICES:
        raise ValueError(
            f"Unsupported assistant voice: {assistant_voice!r}"
        )

    business = Business(
        business_id=BUSINESS_ID,
        name=BUSINESS_NAME,
        owner_name=owner_name,
        assistant_name=assistant_name,
        assistant_voice=assistant_voice,
    )

    ai_provider = build_ai_provider()

    processor = AssistantProcessor(
        ai_provider=ai_provider,
        validator=AIInterpretationValidator(),
    )

    operation = TargetRoutedOperation(
        operations_by_target={
            "assistant": AssistantConversationOperation(),
            "appointment": AppointmentOperation(),
        }
    )

    executor = ActionExecutor(
        policy=ActionPolicy(),
        operation=operation,
    )

    orchestrator = AssistantOrchestrator(
        business=business,
        processor=processor,
        executor=executor,
    )

    return business, orchestrator


def prompt_for_owner_name() -> str:
    """Ask the business owner what they'd like to be called."""

    while True:
        owner_name = input("What should your assistant call you? ").strip()

        if owner_name:
            return owner_name

        print("Please enter a name.")


def prompt_for_assistant_identity() -> tuple[str, str]:
    """
    Ask the business owner to name their assistant and choose a voice.

    The assistant has no fixed name or identity of its own — these are
    business configuration values chosen at onboarding, never hardcoded.
    """
    while True:
        assistant_name = input(
            "What would you like to name your assistant? "
        ).strip()

        if assistant_name:
            break

        print("Please enter a name.")

    while True:
        assistant_voice = input(
            f"Choose a voice for {assistant_name} "
            f"({'/'.join(SUPPORTED_VOICES)}): "
        ).strip().lower()

        if assistant_voice in SUPPORTED_VOICES:
            break

        print(f"Please choose one of: {', '.join(SUPPORTED_VOICES)}")

    return assistant_name, assistant_voice
