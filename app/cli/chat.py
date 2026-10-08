from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

from app.assistant.message import AssistantMessage
from app.assistant.orchestrator import AssistantOrchestrator
from app.auth.cli import database_path, prompt_login, prompt_signup
from app.auth.errors import AuthenticationError
from app.identity.tenant import TenantContext
from app.persistence.business_repository import SQLiteBusinessRepository
from app.persistence.database import SQLiteDatabase
from app.cli.assistant_factory import build_orchestrator_for_business


_CONFIRMATION_MARKER = "Confirmation ID: "


def _handle_message(
    assistant: AssistantOrchestrator,
    tenant: TenantContext,
    assistant_name: str,
    text: str,
) -> None:
    message = AssistantMessage(
        business_id=tenant.business_id,
        content=text,
    )

    try:
        response = assistant.handle(
            message,
            tenant=tenant,
            channel="cli",
        )
    except PermissionError:
        print(
            f"{assistant_name}: I couldn't process that request."
        )
        return
    except Exception:
        print(
            f"{assistant_name}: I couldn't process that request."
        )
        return

    confirmation_id = _extract_confirmation_id(response.message)

    if confirmation_id is None:
        print(
            f"{response.assistant_name}: {response.message}"
        )
        return

    print(
        f"{response.assistant_name}: {response.message}"
    )

    confirm = input(
        f"{assistant_name}: Proceed? (yes/no) "
    ).strip().lower()

    if confirm not in {"y", "yes"}:
        print(
            f"{assistant_name}: Okay, I won't proceed with that."
        )
        return

    try:
        response = assistant.handle(
            message,
            tenant=tenant,
            channel="cli",
            confirmation_id=confirmation_id,
        )
        print(
            f"{response.assistant_name}: {response.message}"
        )
    except Exception:
        print(
            f"{assistant_name}: I couldn't complete that request."
        )


def _extract_confirmation_id(message: str) -> str | None:
    if not isinstance(message, str):
        return None

    if _CONFIRMATION_MARKER not in message:
        return None

    confirmation_id = message.split(
        _CONFIRMATION_MARKER,
        1,
    )[1].strip()

    return confirmation_id or None


def main() -> None:
    database = SQLiteDatabase(database_path())
    database.initialize()

    print()
    print("========================================")
    print("       AI Business Assistant")
    print("========================================")
    print("1. Create business account")
    print("2. Log in")

    choice = input("Choose: ").strip()

    if choice == "1":
        try:
            user, _, _, _ = prompt_signup(database)
            print(f"\nAccount created for {user.email}.")
        except Exception as exc:
            print(
                f"Signup failed: {type(exc).__name__}: {exc}"
            )
            return

        print("Please log in with your new account.")

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

    _, assistant = build_orchestrator_for_business(business)

    print()
    print(f"Owner: {business.owner_name}")
    print(f"Assistant: {business.assistant_name}")
    print(f"Voice profile: {business.assistant_voice}")
    print("Type 'exit' or 'quit' to end.")
    print()

    while True:
        try:
            text = input(
                f"{business.owner_name}: "
            ).strip()
        except (EOFError, KeyboardInterrupt):
            print(
                f"\n{business.assistant_name}: "
                f"Goodbye, {business.owner_name}."
            )
            break

        if not text:
            continue

        if text.lower() in {"exit", "quit"}:
            print(
                f"{business.assistant_name}: "
                f"Goodbye, {business.owner_name}."
            )
            break

        _handle_message(
            assistant,
            tenant,
            business.assistant_name,
            text,
        )


if __name__ == "__main__":
    main()
