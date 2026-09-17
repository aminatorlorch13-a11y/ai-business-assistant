from __future__ import annotations

from pathlib import Path
import os

from app.auth.errors import AuthenticationError, BusinessSelectionRequired
from app.auth.service import AuthenticationService
from app.auth.signup import SQLiteSignupTransaction
from app.models.business import Business
from app.persistence.business_repository import SQLiteBusinessRepository
from app.persistence.credential_repository import SQLiteCredentialRepository
from app.persistence.database import SQLiteDatabase
from app.persistence.membership_repository import SQLiteMembershipRepository
from app.persistence.session import SQLiteSessionRepository
from app.persistence.user_repository import SQLiteUserRepository
from app.auth.rate_limit import SQLiteAuthenticationRateLimiter

DEFAULT_DB_PATH = Path("data/assistant.sqlite3")


def database_path() -> Path:
    return Path(os.getenv("ASSISTANT_DB_PATH", str(DEFAULT_DB_PATH)))


def build_authentication_service(database: SQLiteDatabase) -> AuthenticationService:
    return AuthenticationService(
        users=SQLiteUserRepository(database),
        credentials=SQLiteCredentialRepository(database),
        memberships=SQLiteMembershipRepository(database),
        sessions=SQLiteSessionRepository(database),
        rate_limiter=SQLiteAuthenticationRateLimiter(database),
    )


def prompt_signup(database: SQLiteDatabase):
    print("\nCreate your business account")
    display_name = input("Your name: ").strip()
    email = input("Email: ").strip()
    password = _prompt_password("Password (minimum 12 characters): ")
    password_again = _prompt_password("Confirm password: ")
    if password != password_again:
        raise ValueError("Passwords do not match.")
    business_name = input("Business name: ").strip()
    assistant_name = input("Assistant name: ").strip()
    assistant_voice = input("Assistant voice (male/female): ").strip().lower()
    return SQLiteSignupTransaction(database).signup(
        display_name=display_name,
        email=email,
        password=password,
        business_name=business_name,
        assistant_name=assistant_name,
        assistant_voice=assistant_voice,
    )


def prompt_login(database: SQLiteDatabase):
    email = input("Email: ").strip()
    password = _prompt_password("Password: ")
    service = build_authentication_service(database)
    try:
        principal = service.login(email, password, source_key="cli")
    except BusinessSelectionRequired as exc:
        print("Choose a business:")
        for index, choice in enumerate(exc.memberships, start=1):
            print(f"  {index}. {choice[0]} ({choice[1]})")
        selected = int(input("Business number: ").strip())
        if selected < 1 or selected > len(exc.memberships):
            raise AuthenticationError() from None
        business_id = exc.memberships[selected - 1][0]
        principal = service.login(email, password, business_id=business_id, source_key="cli")
    return service, principal


def _prompt_password(prompt: str) -> str:
    import getpass
    return getpass.getpass(prompt)
