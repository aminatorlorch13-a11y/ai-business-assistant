from __future__ import annotations

from dotenv import load_dotenv
load_dotenv()

from app.assistant.message import AssistantMessage
from app.assistant.orchestrator import AssistantOrchestrator
from app.auth.cli import database_path, prompt_login, prompt_signup
from app.auth.errors import AuthenticationError
from app.persistence.business_repository import SQLiteBusinessRepository
from app.persistence.database import SQLiteDatabase
from app.cli.assistant_factory import build_orchestrator_for_business


def _handle_message(assistant: AssistantOrchestrator, business_id: str, assistant_name: str, text: str) -> None:
    message = AssistantMessage(business_id=business_id, content=text)
    try:
        response = assistant.handle(message)
        print(f"{response.assistant_name}: {response.message}")
        return
    except PermissionError as exc:
        if "requires confirmation" not in str(exc):
            print(f"{assistant_name}: I couldn't process that request.")
            return

    confirm = input(f"{assistant_name}: This action needs your confirmation. Proceed? (yes/no) ").strip().lower()
    if confirm not in {"y", "yes"}:
        print(f"{assistant_name}: Okay, I won't proceed with that.")
        return
    try:
        response = assistant.handle(message, confirmed=True)
        print(f"{response.assistant_name}: {response.message}")
    except Exception:
        print(f"{assistant_name}: I couldn't complete that request.")


def main() -> None:
    database = SQLiteDatabase(database_path())
    database.initialize()

    print()
    print("========================================")
    print("       AI Business Assistant Setup")
    print("========================================")
    print("1. Create business account")
    print("2. Log in")
    choice = input("Choose: ").strip()

    if choice == "1":
        try:
            user, business, _, _ = prompt_signup(database)
            print(f"\nAccount created for {user.email}.")
        except Exception as exc:
            print(f"Signup failed: {type(exc).__name__}: {exc}")
            return
    elif choice == "2":
        try:
            auth_service, principal = prompt_login(database)
            business = SQLiteBusinessRepository(database).get(principal.business_id)
            if business is None:
                print("Authentication succeeded but the selected business no longer exists.")
                return
        except (AuthenticationError, ValueError) as exc:
            print(f"Login failed: {exc}")
            return
    else:
        print("Please choose 1 or 2.")
        return

    _, assistant = build_orchestrator_for_business(business)
    print()
    print(f"Owner: {business.owner_name}")
    print(f"Assistant: {business.assistant_name}")
    print(f"Voice profile: {business.assistant_voice}")
    print("Type 'exit' or 'quit' to end.")
    print()

    while True:
        try:
            text = input(f"{business.owner_name}: ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{business.assistant_name}: Goodbye, {business.owner_name}.")
            break
        if not text:
            continue
        if text.lower() in {"exit", "quit"}:
            print(f"{business.assistant_name}: Goodbye, {business.owner_name}.")
            break
        _handle_message(assistant, business.business_id, business.assistant_name, text)


if __name__ == "__main__":
    main()
