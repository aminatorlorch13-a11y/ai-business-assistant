from __future__ import annotations

from dotenv import load_dotenv
load_dotenv()

from app.assistant.message import AssistantMessage
from app.assistant.orchestrator import AssistantOrchestrator
from app.cli.assistant_factory import (
    BUSINESS_ID,
    build_business_and_orchestrator,
    prompt_for_assistant_identity,
    prompt_for_owner_name,
)


def _handle_message(
    assistant: AssistantOrchestrator,
    business_id: str,
    assistant_name: str,
    text: str,
) -> None:
    """Send one message to the assistant, prompting for confirmation
    if the requested action requires it before proceeding."""

    message = AssistantMessage(
        business_id=business_id,
        content=text,
    )

    try:
        response = assistant.handle(message)
        print(f"{response.assistant_name}: {response.message}")
        return

    except PermissionError as exc:
        if "requires confirmation" not in str(exc):
            print(
                f"{assistant_name}: I couldn't process that request."
                f" ({type(exc).__name__}: {exc})"
            )
            return

    confirm = input(
        f"{assistant_name}: This action needs your confirmation. Proceed? (yes/no) "
    ).strip().lower()

    if confirm not in {"y", "yes"}:
        print(f"{assistant_name}: Okay, I won't proceed with that.")
        return

    try:
        response = assistant.handle(message, confirmed=True)
        print(f"{response.assistant_name}: {response.message}")

    except Exception as exc:
        print(
            f"{assistant_name}: I couldn't complete that request."
            f" ({type(exc).__name__}: {exc})"
        )


def main() -> None:
    """Start the interactive terminal assistant."""

    print()
    print("========================================")
    print("       AI Business Assistant Setup")
    print("========================================")

    owner_name = prompt_for_owner_name()
    assistant_name, assistant_voice = prompt_for_assistant_identity()

    _, assistant = build_business_and_orchestrator(
        owner_name=owner_name,
        assistant_name=assistant_name,
        assistant_voice=assistant_voice,
    )

    print()
    print(f"Owner: {owner_name}")
    print(f"Assistant: {assistant_name}")
    print(f"Voice profile: {assistant_voice}")
    print("Type 'exit' or 'quit' to end.")
    print()

    while True:
        try:
            text = input(f"{owner_name}: ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{assistant_name}: Goodbye, {owner_name}.")
            break

        if not text:
            continue

        if text.lower() in {"exit", "quit"}:
            print(f"{assistant_name}: Goodbye, {owner_name}.")
            break

        try:
            _handle_message(
                assistant,
                BUSINESS_ID,
                assistant_name,
                text,
            )
        except Exception as exc:
            print(
                f"{assistant_name}: I couldn't process that request."
                f" ({type(exc).__name__}: {exc})"
            )


if __name__ == "__main__":
    main()
