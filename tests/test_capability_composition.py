import pytest

from app.assistant.capability import Capability
from app.assistant.capability_composition import (
    ProductionCapabilityComposition,
    build_production_capability_composition,
)
from app.assistant.capability_router import CapabilityRouter
from app.commercial.entitlement_resolver import EntitlementResolutionError
from app.models.business import Business
from app.persistence.business_repository import SQLiteBusinessRepository
from app.persistence.capability_entitlement_repository import (
    SQLiteCapabilityEntitlementRepository,
)
from app.persistence.database import SQLiteDatabase
from app.trust.capability_executor import CapabilityExecutor
from app.trust.capability_operation_policy import CapabilityOperationPolicy


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


def make_composition(tmp_path, capabilities=None):
    database = make_database(tmp_path)
    seed_business(database, "business-1")

    if capabilities is None:
        capabilities = frozenset({Capability.MEMORY})

    repository = SQLiteCapabilityEntitlementRepository(database)
    repository.configure("business-1", capabilities)

    composition = build_production_capability_composition(
        database=database,
    )

    return database, repository, composition


def test_production_composition_builds_real_capability_stack(tmp_path):
    _, _, composition = make_composition(tmp_path)

    assert isinstance(composition, ProductionCapabilityComposition)
    assert isinstance(composition.router, CapabilityRouter)
    assert isinstance(composition.operation_policy, CapabilityOperationPolicy)


def test_production_composition_registers_only_real_operations(tmp_path):
    _, _, composition = make_composition(tmp_path)

    assert composition.router.supports(Capability.MEMORY) is True
    assert composition.router.supports_operation(
        Capability.MEMORY, "save"
    ) is True
    assert composition.router.supports_operation(
        Capability.MEMORY, "get"
    ) is True
    assert composition.router.supports_operation(
        Capability.MEMORY, "list"
    ) is True
    assert composition.router.supports_operation(
        Capability.MEMORY, "delete"
    ) is True

    assert composition.router.supports(Capability.RESEARCH) is False
    assert composition.router.supports(Capability.CALENDAR) is False


def test_policy_for_business_uses_explicit_entitlements(tmp_path):
    _, _, composition = make_composition(
        tmp_path,
        frozenset({Capability.MEMORY}),
    )

    policy = composition.policy_for_business("business-1")

    assert policy.business_id == "business-1"
    assert policy.allowed_capabilities == frozenset({Capability.MEMORY})


def test_policy_does_not_infer_unlisted_capabilities(tmp_path):
    _, _, composition = make_composition(
        tmp_path,
        frozenset({Capability.MEMORY}),
    )

    policy = composition.policy_for_business("business-1")

    assert Capability.CALENDAR not in policy.allowed_capabilities
    assert Capability.RESEARCH not in policy.allowed_capabilities
    assert Capability.MAPS not in policy.allowed_capabilities


def test_configured_business_with_zero_capabilities_gets_empty_policy(tmp_path):
    _, _, composition = make_composition(tmp_path, frozenset())

    policy = composition.policy_for_business("business-1")

    assert policy.allowed_capabilities == frozenset()


def test_unconfigured_business_cannot_get_execution_policy(tmp_path):
    _, _, composition = make_composition(tmp_path)

    with pytest.raises(
        EntitlementResolutionError,
        match="not configured",
    ):
        composition.policy_for_business("business-2")


def test_executor_for_business_is_real_capability_executor(tmp_path):
    _, _, composition = make_composition(tmp_path)

    executor = composition.executor_for_business("business-1")

    assert isinstance(executor, CapabilityExecutor)


def test_memory_confirmation_policy_is_application_owned(tmp_path):
    _, _, composition = make_composition(tmp_path)

    assert composition.operation_policy.requires_confirmation(
        Capability.MEMORY, "save"
    ) is True

    assert composition.operation_policy.requires_confirmation(
        Capability.MEMORY, "get"
    ) is False

    assert composition.operation_policy.requires_confirmation(
        Capability.MEMORY, "list"
    ) is False

    assert composition.operation_policy.requires_confirmation(
        Capability.MEMORY, "delete"
    ) is True


def test_composition_rejects_invalid_database_at_runtime(tmp_path):
    with pytest.raises(
        TypeError,
        match="database must be a SQLiteDatabase",
    ):
        build_production_capability_composition(
            database=object(),
        )
