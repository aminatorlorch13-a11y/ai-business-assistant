import pytest

from app.assistant.capability import Capability
from app.commercial.entitlement_resolver import (
    EntitlementResolutionError,
    ExplicitEntitlementResolver,
)


def test_resolver_returns_explicit_business_entitlements():
    resolver = ExplicitEntitlementResolver(
        {
            "business-1": frozenset(
                {
                    Capability.MEMORY,
                    Capability.CALCULATOR,
                }
            ),
        }
    )

    result = resolver.resolve("business-1")

    assert result.business_id == "business-1"
    assert result.capabilities == frozenset(
        {
            Capability.MEMORY,
            Capability.CALCULATOR,
        }
    )


def test_resolver_normalizes_business_id():
    resolver = ExplicitEntitlementResolver(
        {
            "business-1": frozenset({Capability.MEMORY}),
        }
    )

    result = resolver.resolve("  business-1  ")

    assert result.business_id == "business-1"


def test_unconfigured_business_is_denied():
    resolver = ExplicitEntitlementResolver(
        {
            "business-1": frozenset({Capability.MEMORY}),
        }
    )

    with pytest.raises(
        EntitlementResolutionError,
        match="not configured",
    ):
        resolver.resolve("business-2")


def test_empty_business_id_is_rejected():
    resolver = ExplicitEntitlementResolver({})

    with pytest.raises(ValueError, match="non-empty"):
        resolver.resolve("   ")


def test_invalid_capability_mapping_is_rejected():
    with pytest.raises(TypeError, match="frozensets"):
        ExplicitEntitlementResolver(
            {
                "business-1": {Capability.MEMORY},
            }
        )


def test_invalid_capability_value_is_rejected():
    with pytest.raises(TypeError, match="Capability"):
        ExplicitEntitlementResolver(
            {
                "business-1": frozenset({"memory"}),
            }
        )


def test_resolver_does_not_add_capabilities_not_explicitly_granted():
    resolver = ExplicitEntitlementResolver(
        {
            "business-1": frozenset({Capability.MEMORY}),
        }
    )

    result = resolver.resolve("business-1")

    assert result.capabilities == frozenset({Capability.MEMORY})
    assert Capability.CALENDAR not in result.capabilities
    assert Capability.RESEARCH not in result.capabilities
