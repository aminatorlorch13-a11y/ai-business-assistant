from __future__ import annotations

from dotenv import load_dotenv
load_dotenv()

from app.assistant.response import AssistantResponse
from app.cli.assistant_factory import (
    BUSINESS_ID,
    build_business_and_orchestrator,
    prompt_for_assistant_identity,
    prompt_for_owner_name,
)
from app.models.voice import VoiceConfiguration
from app.voice.conversation import ConversationState
from app.voice.input import ConversationInput, ConversationInputSource
from app.voice.local_engine import AndroidSpeechEngine
from app.voice.message_adapter import ConversationMessageAdapter
from app.voice.android_input_engine import AndroidSpeechInputEngine
from app.voice.service import VoiceService
from app.voice.session import ConversationSession


CONFIRMATION_WORDS = {"yes", "y", "yeah", "yep", "sure", "go ahead", "confirm"}



def _speak(
    voice_service: VoiceService,
    speech_engine: AndroidSpeechEngine,
    voice_configuration: VoiceConfiguration,
    business_id: str,
    assistant_name: str,
    text: str,
) -> None:
    """Speak a piece of assistant text through the real voice pipeline."""

    response = AssistantResponse(
        business_id=business_id,
        assistant_name=assistant_name,
        message=text,
    )

    speech_request = voice_service.create_speech_request(
        response,
        voice_configuration,
    )

    speech_engine.speak(speech_request)


def main() -> None:
    """Run a real listen -> understand -> speak voice conversation."""

    print()
    print("========================================")
    print("       AI Business Assistant Setup")
    print("========================================")

    owner_name = prompt_for_owner_name()
    assistant_name, assistant_voice = prompt_for_assistant_identity()

    business, orchestrator = build_business_and_orchestrator(
        owner_name=owner_name,
        assistant_name=assistant_name,
        assistant_voice=assistant_voice,
    )

    speech_input_engine = AndroidSpeechInputEngine()
    speech_engine = AndroidSpeechEngine()
    voice_service = VoiceService()
    voice_configuration = VoiceConfiguration(voice=assistant_voice)
    message_adapter = ConversationMessageAdapter()

    session = ConversationSession()

    print()
    print(f"{assistant_name} is now listening. Speak naturally.")
    print("Say 'exit' or 'quit' to end.")
    print()

    while session.state != ConversationState.ENDED:
        try:
            session.start_listening()

            print("Listening...")
            speech_input = speech_input_engine.listen()
            text = speech_input.text
            print(f"{owner_name}: {text}")

            if text.strip().lower() in {"exit", "quit"}:
                farewell = f"Goodbye, {owner_name}."
                print(f"{assistant_name}: {farewell}")
                _speak(
                    voice_service,
                    speech_engine,
                    voice_configuration,
                    BUSINESS_ID,
                    assistant_name,
                    farewell,
                )
                session.stop()
                break

            session.start_processing()

            conversation_input = ConversationInput(
                text=text,
                source=ConversationInputSource.VOICE,
            )

            assistant_message = message_adapter.to_assistant_message(
                conversation_input,
                BUSINESS_ID,
            )

            try:
                response = orchestrator.handle(assistant_message)

            except PermissionError as exc:
                if "requires confirmation" not in str(exc):
                    raise

                question = (
                    "This action needs your confirmation. "
                    "Please say yes or no."
                )
                print(f"{assistant_name}: {question}")

                session.start_speaking()
                _speak(
                    voice_service,
                    speech_engine,
                    voice_configuration,
                    BUSINESS_ID,
                    assistant_name,
                    question,
                )

                session.wait_for_input()
                session.start_listening()

                print("Listening for confirmation...")
                confirmation_input = speech_input_engine.listen()
                confirmation_text = confirmation_input.text.strip().lower()
                print(f"{owner_name}: {confirmation_text}")

                session.start_processing()

                if confirmation_text in CONFIRMATION_WORDS:
                    response = orchestrator.handle(
                        assistant_message,
                        confirmed=True,
                    )
                else:
                    decline_text = "Okay, I won't proceed with that."
                    session.start_speaking()
                    print(f"{assistant_name}: {decline_text}")
                    _speak(
                        voice_service,
                        speech_engine,
                        voice_configuration,
                        BUSINESS_ID,
                        assistant_name,
                        decline_text,
                    )
                    session.wait_for_input()
                    continue

            print(f"{assistant_name}: {response.message}")

            session.start_speaking()
            _speak(
                voice_service,
                speech_engine,
                voice_configuration,
                BUSINESS_ID,
                assistant_name,
                response.message,
            )

            session.wait_for_input()

        except (EOFError, KeyboardInterrupt):
            farewell = f"Goodbye, {owner_name}."
            print(f"\n{assistant_name}: {farewell}")
            if session.state not in {ConversationState.ENDED}:
                session.stop()
            break

        except Exception as exc:
            print(
                f"{assistant_name}: I couldn't process that."
                f" ({type(exc).__name__}: {exc})"
            )
            if session.state != ConversationState.ENDED:
                session.fail()
                session.recover_to_input()


if __name__ == "__main__":
    main()
