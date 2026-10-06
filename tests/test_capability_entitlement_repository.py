import sqlite3
import pytest

from app.assistant.capability import Capability
from app.models.business import Business
from app.persistence.business_repository import SQLiteBusinessRepository
from app.persistence.capability_entitlement_repository import (
    SQLiteCapabilityEntitlementRepository,
)
from app.persistence.database import SQLiteDatabase


def make_database(tmp_path):
    database = SQLiteDatabase(tmp_path / "assistant.sqlite3")
    database.initialize()
    return database


def make_business(business_id):
    return Business(
        business_id,
        f"Business {business_id}",
        "Owner",
        "Test Assistant",
        "male",
    )


def seed_business(database, business_id):
    SQLiteBusinessRepository(database).save(make_business(business_id))


def make_repository(tmp_path):
    database = make_database(tmp_path)
    return database, SQLiteCapabilityEntitlementRepository(database)


def test_unconfigured_business_returns_none(tmp_path):
    _, repository = make_repository(tmp_path)

    assert repository.get("business-1") is None
    assert repository.is_configured("business-1") is False


def test_configure_persists_exact_capabilities(tmp_path):
    database, repository = make_repository(tmp_path)
    seed_business(database, "business-1")

    repository.configure(
        "business-1",
        frozenset({Capability.MEMORY, Capability.CALCULATOR}),
    )

    assert repository.is_configured("business-1") is True
    assert repository.get("business-1") == frozenset(
        {Capability.MEMORY, Capability.CALCULATOR}
    )


def test_configured_business_can_have_zero_capabilities(tmp_path):
    database, repository = make_repository(tmp_path)
    seed_business(database, "business-1")

    repository.configure("business-1", frozenset())

    assert repository.is_configured("business-1") is True
    assert repository.get("business-1") == frozenset()


def test_configure_replaces_existing_grants(tmp_path):
    database, repository = make_repository(tmp_path)
    seed_business(database, "business-1")

    repository.configure(
        "business-1",
        frozenset({Capability.MEMORY}),
    )
    repository.configure(
        "business-1",
        frozenset({Capability.CALCULATOR}),
    )

    assert repository.get("business-1") == frozenset(
        {Capability.CALCULATOR}
    )


def test_grant_requires_prior_configuration(tmp_path):
    _, repository = make_repository(tmp_path)

    with pytest.raises(ValueError, match="explicitly configured"):
        repository.grant("business-1", Capability.MEMORY)


def test_configure_requires_existing_business(tmp_path):
    _, repository = make_repository(tmp_path)

    with pytest.raises(sqlite3.IntegrityError):
        repository.configure(
            "missing-business",
            frozenset({Capability.MEMORY}),
        )


def test_grant_is_idempotent(tmp_path):
    database, repository = make_repository(tmp_path)
    seed_business(database, "business-1")

    repository.configure("business-1", frozenset())

    repository.grant("business-1", Capability.MEMORY)
    repository.grant("business-1", Capability.MEMORY)

    assert repository.get("business-1") == frozenset({Capability.MEMORY})


def test_revoke_returns_true_only_when_grant_existed(tmp_path):
    database, repository = make_repository(tmp_path)
    seed_business(database, "business-1")

    repository.configure(
        "business-1",
        frozenset({Capability.MEMORY}),
    )

    assert repository.revoke("business-1", Capability.MEMORY) is True
    assert repository.revoke("business-1", Capability.MEMORY) is False
    assert repository.get("business-1") == frozenset()


def test_revoke_does_not_remove_configuration(tmp_path):
    database, repository = make_repository(tmp_path)
    seed_business(database, "business-1")

    repository.configure(
        "business-1",
        frozenset({Capability.MEMORY}),
    )
    repository.revoke("business-1", Capability.MEMORY)

    assert repository.is_configured("business-1") is True
    assert repository.get("business-1") == frozenset()


def test_invalid_business_id_is_rejected(tmp_path):
    _, repository = make_repository(tmp_path)

    with pytest.raises(TypeError):
        repository.get(123)

    with pytest.raises(ValueError):
        repository.get("   ")


def test_invalid_capability_is_rejected(tmp_path):
    database, repository = make_repository(tmp_path)
    seed_business(database, "business-1")

    repository.configure("business-1", frozenset())

    with pytest.raises(TypeError):
        repository.grant("business-1", "memory")


def test_non_frozenset_capabilities_are_rejected(tmp_path):
    _, repository = make_repository(tmp_path)

    with pytest.raises(TypeError, match="frozenset"):
        repository.configure(
            "business-1",
            {Capability.MEMORY},
        )


def test_invalid_capability_value_in_set_is_rejected(tmp_path):
    _, repository = make_repository(tmp_path)

    with pytest.raises(TypeError, match="Capability"):
        repository.configure(
            "business-1",
            frozenset({"memory"}),
        )


def test_configuration_is_tenant_scoped(tmp_path):
    database, repository = make_repository(tmp_path)
    seed_business(database, "business-1")
    seed_business(database, "business-2")

    repository.configure(
        "business-1",
        frozenset({Capability.MEMORY}),
    )
    repository.configure(
        "business-2",
        frozenset({Capability.CALCULATOR}),
    )

    assert repository.get("business-1") == frozenset({Capability.MEMORY})
    assert repository.get("business-2") == frozenset({Capability.CALCULATOR})


def test_database_persistence_survives_repository_recreation(tmp_path):
    database = make_database(tmp_path)
    seed_business(database, "business-1")

    repository_one = SQLiteCapabilityEntitlementRepository(database)
    repository_one.configure(
        "business-1",
        frozenset({Capability.MEMORY}),
    )

    repository_two = SQLiteCapabilityEntitlementRepository(database)

    assert repository_two.get("business-1") == frozenset({Capability.MEMORY})


def test_business_id_is_normalized(tmp_path):
    database = make_database(tmp_path)
    seed_business(database, "business-1")

    repository = SQLiteCapabilityEntitlementRepository(database)

    repository.configure(
        " business-1 ",
        frozenset({Capability.MEMORY}),
    )

    assert repository.is_configured("business-1")
    assert repository.get(" business-1 ") == frozenset({Capability.MEMORY})
