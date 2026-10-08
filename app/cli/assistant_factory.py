from __future__ import annotations

import os

from app.ai.groq_config import GroqConfig
from app.ai.groq_provider import GroqHTTPProvider
from app.ai.structured_provider import ParsedRawAIProvider
from app.assistant.capability_confirmation_service import (
    CapabilityConfirmationService,
)
from app.assistant.capability_composition import (
    build_production_capability_composition,
)
from app.assistant.orchestrator import AssistantOrchestrator
from app.assistant.structured_processor import StructuredAssistantProcessor
from app.models.business import Business
from app.models.voice import SUPPORTED_VOICES
from app.persistence.capability_confirmation import (
    SQLiteCapabilityConfirmationRepository,
)
from app.persistence.database import SQLiteDatabase
from app.memory.context import MemoryContextBuilder
from app.commercial.access import BusinessAccessService


def _production_database() -> SQLiteDatabase:
    """Open the authoritative production application database."""
    database = SQLiteDatabase(
        os.getenv(
            "ASSISTANT_DB_PATH",
            "data/assistant.sqlite3",
        )
    )
    database.initialize()
    return database


def build_ai_provider() -> ParsedRawAIProvider:
    """
    Construct the structured production AI provider.

    The provider produces only an untrusted AIResult. It does not receive
    tenant authority and cannot execute capabilities.
    """
    try:
        config = GroqConfig.from_environment()
    except RuntimeError as exc:
        raise RuntimeError(
            "Cannot start assistant: Groq is not configured. "
            f"{exc}"
        ) from exc

    return ParsedRawAIProvider(
        GroqHTTPProvider(config)
    )


def build_orchestrator_for_business(
    business: Business,
) -> tuple[Business, AssistantOrchestrator]:
    """
    Build the canonical structured production assistant runtime.

    The supplied Business must come from the authenticated application's
    authoritative business repository. This factory does not create or
    invent tenant identity.
    """
    if not isinstance(business, Business):
        raise TypeError("business must be a Business.")

    database = _production_database()

    structured_provider = build_ai_provider()

    capability_composition = build_production_capability_composition(
        database=database,
    )

    memory_context_builder = MemoryContextBuilder(
        capability_composition.memory_service,
    )

    processor = StructuredAssistantProcessor(
        ai_provider=structured_provider,
        memory_context_builder=memory_context_builder,
    )

    confirmation_repository = SQLiteCapabilityConfirmationRepository(
        database,
    )

    confirmation_service = CapabilityConfirmationService(
        confirmation_repository,
    )

    commercial_access = BusinessAccessService(database)

    executor = capability_composition.executor_for_business(
        business.business_id,
    )

    orchestrator = AssistantOrchestrator(
        business=business,
        processor=processor,
        executor=executor,
        capability_operation_policy=(
            capability_composition.operation_policy
        ),
        confirmation_service=confirmation_service,
        commercial_access=commercial_access,
    )

    return business, orchestrator


def prompt_for_owner_name() -> str:
    """Ask the business owner what they'd like to be called."""
    while True:
        owner_name = input(
            "What should your assistant call you? "
        ).strip()

        if owner_name:
            return owner_name

        print("Please enter a name.")


def prompt_for_assistant_identity() -> tuple[str, str]:
    """
    Ask the business owner to name their assistant and choose a voice.

    The assistant has no fixed application-owned name or identity.
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

        print(
            f"Please choose one of: {', '.join(SUPPORTED_VOICES)}"
        )

    return assistant_name, assistant_voice
