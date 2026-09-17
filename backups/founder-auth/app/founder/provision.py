from __future__ import annotations

import argparse
import os
from pathlib import Path

from app.founder.models import FounderRecord
from app.persistence.database import SQLiteDatabase
from app.persistence.founder_repository import SQLiteFounderRepository
from app.persistence.user_repository import SQLiteUserRepository


DEFAULT_DB_PATH = Path("data/assistant.sqlite3")


class FounderProvisioningDisabled(PermissionError):
    """Founder provisioning is not explicitly enabled."""


def database_path() -> Path:
    return Path(
        os.getenv(
            "ASSISTANT_DB_PATH",
            str(DEFAULT_DB_PATH),
        )
    )


def provisioning_enabled() -> bool:
    return (
        os.getenv("FOUNDER_PROVISIONING_CLI", "").strip().lower()
        == "true"
    )


def require_provisioning_enabled() -> None:
    if not provisioning_enabled():
        raise FounderProvisioningDisabled(
            "FOUNDER_PROVISIONING_CLI is not enabled."
        )

    environment = os.getenv(
        "APP_ENV",
        "development",
    ).strip().lower()

    if environment not in {"development", "test", "production"}:
        raise FounderProvisioningDisabled(
            "Founder provisioning is unavailable in this environment."
        )


def provision_founder(
    email: str,
    *,
    confirmed: bool = False,
    reactivate: bool = False,
) -> str:
    require_provisioning_enabled()

    if not isinstance(email, str) or not email.strip():
        raise ValueError("email must be a non-empty string.")

    if not isinstance(confirmed, bool):
        raise TypeError("confirmed must be a bool.")

    if not confirmed:
        raise PermissionError(
            "Founder provisioning requires explicit confirmation."
        )

    if not isinstance(reactivate, bool):
        raise TypeError("reactivate must be a bool.")

    database = SQLiteDatabase(database_path())
    database.initialize()

    users = SQLiteUserRepository(database)
    founders = SQLiteFounderRepository(database)

    user = users.get_by_email(email.strip())

    if user is None:
        raise LookupError(
            "No existing user matches that email."
        )

    existing = founders.get(user.user_id)

    if existing is not None:
        if existing.active:
            raise PermissionError(
                "User already has active Founder authority."
            )

        if not reactivate:
            raise PermissionError(
                "Inactive Founder authority exists; "
                "explicit reactivation is required."
            )

    founders.save(
        FounderRecord(
            user_id=user.user_id,
            active=True,
        )
    )

    return user.user_id


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Provision an existing user as a platform Founder."
        )
    )
    parser.add_argument(
        "--email",
        required=True,
        help="Existing user email.",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Explicitly confirm the Founder authority grant.",
    )
    parser.add_argument(
        "--reactivate",
        action="store_true",
        help=(
            "Explicitly reactivate an existing inactive Founder record."
        ),
    )

    args = parser.parse_args()

    user_id = provision_founder(
        args.email,
        confirmed=args.confirm,
        reactivate=args.reactivate,
    )

    print(f"Founder authority provisioned for user {user_id}.")


if __name__ == "__main__":
    main()
