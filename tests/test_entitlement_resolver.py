import pytest

from app.assistant.capability import Capability
from app.commercial.entitlement_resolver import (
    EntitlementResolutionError,
    ExplicitEntitlementResolver,
)
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


def make_resolver(tmp_path):
    database = make_database(tmp_path)
    repository = SQLiteCapabilityEntitlementRepository(database)
    resolver = ExplicitEntitlementResolver(repository)
    return database, repository, resolver


def test_resolver_returns_explicit_business_entitlements(tmp_path):
    database, repository, resolver = make_resolver(tmp_path)
    seed_business(database, "business-1")

    repository.configure(
        "business-1",
        frozenset({Capability.MEMORY, Capability.CALCULATOR}),
    )

    result = resolver.resolve("business-1")

    assert result.business_id == "business-1"
    assert result.capabilities == frozenset(
        {Capability.MEMORY, Capability.CALCULATOR}
    )


def test_resolver_normalizes_business_id(tmp_path):
    database, repository, resolver = make_resolver(tmp_path)
    seed_business(database, "business-1")

    repository.configure("business-1", frozenset({Capability.MEMORY}))

    result = resolver.resolve("  business-1  ")

    assert result.business_id == "business-1"


def test_unconfigured_business_is_denied(tmp_path):
    database, repository, resolver = make_resolver(tmp_path)
    seed_business(database, "business-1")

    repository.configure("business-1", frozenset({Capability.MEMORY}))

    with pytest.raises(
        EntitlementResolutionError,
        match="not configured",
    ):
        resolver.resolve("business-2")


def test_empty_business_id_is_rejected(tmp_path):
    _, _, resolver = make_resolver(tmp_path)

    with pytest.raises(ValueError, match="non-empty"):
        resolver.resolve("   ")


def test_configured_business_can_have_zero_capabilities(tmp_path):
    database, repository, resolver = make_resolver(tmp_path)
    seed_business(database, "business-1")

    repository.configure("business-1", frozenset())

    result = resolver.resolve("business-1")

    assert result.business_id == "business-1"
    assert result.capabilities == frozenset()


def test_resolver_does_not_add_unlisted_capabilities(tmp_path):
    database, repository, resolver = make_resolver(tmp_path)
    seed_business(database, "business-1")

    repository.configure("business-1", frozenset({Capability.MEMORY}))

    result = resolver.resolve("business-1")

    assert result.capabilities == frozenset({Capability.MEMORY})
    assert Capability.CALENDAR not in result.capabilities
    assert Capability.RESEARCH not in result.capabilities


def test_resolver_reads_current_durable_grants(tmp_path):
    database, repository, resolver = make_resolver(tmp_path)
    seed_business(database, "business-1")

    repository.configure("business-1", frozenset({Capability.MEMORY}))

    assert resolver.resolve("business-1").capabilities == frozenset(
        {Capability.MEMORY}
    )

    repository.grant("business-1", Capability.CALCULATOR)

    assert resolver.resolve("business-1").capabilities == frozenset(
        {Capability.MEMORY, Capability.CALCULATOR}
    )
