from __future__ import annotations

import pytest

from app.founder.models import FounderRecord
from app.founder import provision
from app.persistence.database import SQLiteDatabase
from app.persistence.founder_repository import SQLiteFounderRepository
from app.persistence.user_repository import SQLiteUserRepository
from app.identity.models import User


def make_database(tmp_path):
    database = SQLiteDatabase(tmp_path / "assistant.sqlite3")
    database.initialize()
    return database


def make_user(database, user_id="user-1", email="user@example.com"):
    users = SQLiteUserRepository(database)
    user = User(
        user_id,
        "Test User",
        email,
    )
    users.save(user)
    return user


def test_provisioning_is_disabled_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv(
        "FOUNDER_PROVISIONING_CLI",
        raising=False,
    )
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv(
        "ASSISTANT_DB_PATH",
        str(tmp_path / "assistant.sqlite3"),
    )

    with pytest.raises(provision.FounderProvisioningDisabled):
        provision.provision_founder(
            "user@example.com",
            confirmed=True,
        )


def test_provisioning_requires_explicit_confirmation(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv(
        "FOUNDER_PROVISIONING_CLI",
        "true",
    )
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv(
        "ASSISTANT_DB_PATH",
        str(tmp_path / "assistant.sqlite3"),
    )

    database = make_database(tmp_path)
    make_user(database)

    with pytest.raises(PermissionError):
        provision.provision_founder(
            "user@example.com",
            confirmed=False,
        )


def test_production_provisioning_requires_explicit_gate(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv(
        "FOUNDER_PROVISIONING_CLI",
        raising=False,
    )
    monkeypatch.setenv(
        "ASSISTANT_DB_PATH",
        str(tmp_path / "assistant.sqlite3"),
    )

    with pytest.raises(provision.FounderProvisioningDisabled):
        provision.provision_founder(
            "user@example.com",
            confirmed=True,
        )


def test_existing_user_is_required(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "FOUNDER_PROVISIONING_CLI",
        "true",
    )
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv(
        "ASSISTANT_DB_PATH",
        str(tmp_path / "assistant.sqlite3"),
    )

    make_database(tmp_path)

    with pytest.raises(LookupError):
        provision.provision_founder(
            "missing@example.com",
            confirmed=True,
        )


def test_active_founder_cannot_be_silently_reprovisioned(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv(
        "FOUNDER_PROVISIONING_CLI",
        "true",
    )
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv(
        "ASSISTANT_DB_PATH",
        str(tmp_path / "assistant.sqlite3"),
    )

    database = make_database(tmp_path)
    user = make_user(database)

    founders = SQLiteFounderRepository(database)
    founders.save(
        FounderRecord(
            user_id=user.user_id,
            active=True,
        )
    )

    with pytest.raises(PermissionError):
        provision.provision_founder(
            user.email,
            confirmed=True,
        )


def test_inactive_founder_requires_explicit_reactivation(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv(
        "FOUNDER_PROVISIONING_CLI",
        "true",
    )
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv(
        "ASSISTANT_DB_PATH",
        str(tmp_path / "assistant.sqlite3"),
    )

    database = make_database(tmp_path)
    user = make_user(database)

    founders = SQLiteFounderRepository(database)
    founders.save(
        FounderRecord(
            user_id=user.user_id,
            active=False,
        )
    )

    with pytest.raises(PermissionError):
        provision.provision_founder(
            user.email,
            confirmed=True,
            reactivate=False,
        )


def test_inactive_founder_can_be_explicitly_reactivated(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv(
        "FOUNDER_PROVISIONING_CLI",
        "true",
    )
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv(
        "ASSISTANT_DB_PATH",
        str(tmp_path / "assistant.sqlite3"),
    )

    database = make_database(tmp_path)
    user = make_user(database)

    founders = SQLiteFounderRepository(database)
    founders.save(
        FounderRecord(
            user_id=user.user_id,
            active=False,
        )
    )

    provision.provision_founder(
        user.email,
        confirmed=True,
        reactivate=True,
    )

    founder = founders.get(user.user_id)

    assert founder is not None
    assert founder.active is True


def test_invalid_environment_is_rejected(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv(
        "FOUNDER_PROVISIONING_CLI",
        "true",
    )
    monkeypatch.setenv("APP_ENV", "unknown")
    monkeypatch.setenv(
        "ASSISTANT_DB_PATH",
        str(tmp_path / "assistant.sqlite3"),
    )

    with pytest.raises(provision.FounderProvisioningDisabled):
        provision.provision_founder(
            "user@example.com",
            confirmed=True,
        )


def test_provisioning_does_not_create_unknown_users(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv(
        "FOUNDER_PROVISIONING_CLI",
        "true",
    )
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv(
        "ASSISTANT_DB_PATH",
        str(tmp_path / "assistant.sqlite3"),
    )

    database = make_database(tmp_path)
    users = SQLiteUserRepository(database)

    with pytest.raises(LookupError):
        provision.provision_founder(
            "attacker@example.com",
            confirmed=True,
        )

    assert users.get_by_email("attacker@example.com") is None


def test_provisioning_creates_founder_only_for_existing_user(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv(
        "FOUNDER_PROVISIONING_CLI",
        "true",
    )
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv(
        "ASSISTANT_DB_PATH",
        str(tmp_path / "assistant.sqlite3"),
    )

    database = make_database(tmp_path)
    user = make_user(database)

    provision.provision_founder(
        user.email,
        confirmed=True,
    )

    founders = SQLiteFounderRepository(database)
    founder = founders.get(user.user_id)

    assert founder is not None
    assert founder.active is True
