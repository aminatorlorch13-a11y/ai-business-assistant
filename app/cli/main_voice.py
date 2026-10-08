from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

from app.auth.cli import database_path, prompt_login, prompt_signup
from app.assistant.response import AssistantResponse
from app.auth.errors import AuthenticationError
from app.commercial.access import BusinessAccessService
from app.identity.tenant import TenantContext
from app.persistence.business_repository import SQLiteBusinessRepository
from app.persistence.database import SQLiteDatabase
from app.voice.conversation import ConversationState
from app.voice.conversation_coordinator import (
    AssistantConversationCoordinator,
)
from app.voice.android_input_engine import AndroidSpeechInputEngine
from app.voice.local_engine import AndroidSpeechEngine
from app.voice.message_adapter import ConversationMessageAdapter
from app.voice.service import VoiceService
from app.voice.session import ConversationSession
from app.models.voice import VoiceConfiguration

from app.cli.assistant_factory import build_orchestrator_for_business


CONFIRMATION_WORDS = {
    "yes",
    "y",
    "yeah",
    "yep",
    "sure",
    "go ahead",
    "confirm",
}


def _extract_confirmation_id(message: str) -> str | None:
    """Extract the durable confirmation ID emitted by Assistant Core."""
    marker = "Confirmation ID: "

    if not isinstance(message, str):
        return None

    if marker not in message:
        return None

    confirmation_id = message.split(marker, 1)[1].strip()

    return confirmation_id or None


def main() -> None:
    """Run an authenticated, structured production voice conversation."""
    database = SQLiteDatabase(database_path())
    database.initialize()

    print()
    print("========================================")
    print("       AI Business Assistant Voice")
    print("========================================")
    print("1. Create business account")
    print("2. Log in")
    choice = input("Choose: ").strip()

    if choice == "1":
        try:
            user, business, _, _ = prompt_signup(database)
            print(f"\nAccount created for {user.email}.")
            print("Please log in with your new account.")
        except Exception as exc:
            print(
                f"Signup failed: {type(exc).__name__}: {exc}"
            )
            return

        try:
            _, principal = prompt_login(database)
        except (AuthenticationError, ValueError) as exc:
            print(f"Login failed: {exc}")
            return

    elif choice == "2":
        try:
            _, principal = prompt_login(database)
        except (AuthenticationError, ValueError) as exc:
            print(f"Login failed: {exc}")
            return

    else:
        print("Please choose 1 or 2.")
        return

    if principal.business_id is None:
        print("Login did not produce a business-scoped session.")
        return

    business = SQLiteBusinessRepository(database).get(
        principal.business_id
    )

    if business is None:
        print(
            "Authentication succeeded but the selected business "
            "no longer exists."
        )
        return

    tenant = TenantContext(
        business_id=business.business_id,
        principal=principal,
    )

    _, orchestrator = build_orchestrator_for_business(business)

    speech_input_engine = AndroidSpeechInputEngine()
    speech_engine = AndroidSpeechEngine()
    voice_service = VoiceService()
    voice_configuration = VoiceConfiguration(
        voice=business.assistant_voice,
    )
    message_adapter = ConversationMessageAdapter()
    commercial_access = BusinessAccessService(database)
    session = ConversationSession()

    coordinator = AssistantConversationCoordinator(
        business=business,
        orchestrator=orchestrator,
        speech_input_engine=speech_input_engine,
        speech_engine=speech_engine,
        voice_service=voice_service,
        voice_configuration=voice_configuration,
        message_adapter=message_adapter,
        commercial_access=commercial_access,
        tenant=tenant,
        session=session,
    )

    owner_name = business.owner_name
    assistant_name = business.assistant_name

    print()
    print(f"Owner: {owner_name}")
    print(f"Assistant: {assistant_name}")
    print(f"Voice profile: {business.assistant_voice}")
    print()
    print(
        f"{assistant_name} is now listening. Speak naturally."
    )
    print("Say 'exit' or 'quit' to end.")
    print()

    while session.state != ConversationState.ENDED:
        try:
            session.start_listening()
            print("Listening...")

            conversation_input = coordinator.capture_voice_input()
            text = conversation_input.text

            print(f"{owner_name}: {text}")

            if text.strip().lower() in {"exit", "quit"}:
                farewell = f"Goodbye, {owner_name}."
                print(f"{assistant_name}: {farewell}")

                coordinator.speak_response(
                    AssistantResponse(
                        business_id=business.business_id,
                        assistant_name=assistant_name,
                        message=farewell,
                    )
                )

                session.stop()
                break

            session.start_processing()

            response = coordinator.process_input(
                conversation_input,
            )

            confirmation_id = _extract_confirmation_id(
                response.message,
            )

            print(
                f"{assistant_name}: {response.message}"
            )

            session.start_speaking()
            coordinator.speak_response(response)

            if confirmation_id is not None:
                session.wait_for_input()

                session.start_listening()
                print("Listening for confirmation...")

                confirmation_input = (
                    coordinator.capture_voice_input()
                )
                confirmation_text = (
                    confirmation_input.text.strip().lower()
                )

                print(
                    f"{owner_name}: {confirmation_text}"
                )

                if confirmation_text in CONFIRMATION_WORDS:
                    session.start_processing()

                    confirmed_response = (
                        coordinator.process_confirmation(
                            confirmation_id,
                        )
                    )

                    print(
                        f"{assistant_name}: "
                        f"{confirmed_response.message}"
                    )

                    session.start_speaking()
                    coordinator.speak_response(
                        confirmed_response,
                    )

                else:
                    decline_text = (
                        "Okay, I won't proceed with that."
                    )

                    print(
                        f"{assistant_name}: {decline_text}"
                    )

                    session.start_speaking()
                    coordinator.speak_response(
                        AssistantResponse(
                            business_id=business.business_id,
                            assistant_name=assistant_name,
                            message=decline_text,
                        )
                    )

                if session.state != ConversationState.ENDED:
                    session.wait_for_input()

        except (EOFError, KeyboardInterrupt):
            farewell = f"Goodbye, {owner_name}."
            print(f"\n{assistant_name}: {farewell}")

            if session.state != ConversationState.ENDED:
                session.stop()

            break

        except Exception as exc:
            print(
                f"{assistant_name}: I couldn't process that."
                f" ({type(exc).__name__}: {exc})"
            )

            if session.state == ConversationState.ENDED:
                break

            if session.state != ConversationState.WAITING:
                session.recover_to_input()

            session.wait_for_input()
