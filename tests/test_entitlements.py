import pytest

from app.assistant.capability import Capability
from app.commercial.entitlements import BusinessEntitlements


def test_valid_entitlements():
    entitlements = BusinessEntitlements(
        business_id="business-1",
        capabilities=frozenset({
            Capability.CONVERSATION,
            Capability.TIME,
            Capability.MEMORY,
        }),
    )

    assert entitlements.business_id == "business-1"
    assert entitlements.includes(Capability.CONVERSATION)
    assert entitlements.includes(Capability.TIME)
    assert entitlements.includes(Capability.MEMORY)
    assert not entitlements.includes(Capability.RESEARCH)


def test_entitlements_are_immutable():
    entitlements = BusinessEntitlements(
        business_id="business-1",
        capabilities=frozenset({
            Capability.CONVERSATION,
        }),
    )

    with pytest.raises(AttributeError):
        entitlements.business_id = "business-2"


def test_business_id_must_be_string():
    with pytest.raises(TypeError):
        BusinessEntitlements(
            business_id=123,
            capabilities=frozenset(),
        )


def test_business_id_must_not_be_empty():
    with pytest.raises(ValueError):
        BusinessEntitlements(
            business_id="   ",
            capabilities=frozenset(),
        )


def test_capabilities_must_be_frozenset():
    with pytest.raises(TypeError):
        BusinessEntitlements(
            business_id="business-1",
            capabilities={Capability.CONVERSATION},
        )


def test_capabilities_must_contain_only_capability_values():
    with pytest.raises(TypeError):
        BusinessEntitlements(
            business_id="business-1",
            capabilities=frozenset({
                Capability.CONVERSATION,
                "research",
            }),
        )


def test_includes_rejects_invalid_capability():
    entitlements = BusinessEntitlements(
        business_id="business-1",
        capabilities=frozenset({
            Capability.CONVERSATION,
        }),
    )

    with pytest.raises(TypeError):
        entitlements.includes("conversation")


def test_empty_entitlements_deny_every_current_capability():
    entitlements = BusinessEntitlements(
        business_id="business-1",
        capabilities=frozenset(),
    )

    for capability in Capability:
        assert not entitlements.includes(capability)


def test_full_entitlements_include_every_current_capability():
    entitlements = BusinessEntitlements(
        business_id="business-1",
        capabilities=frozenset(Capability),
    )

    for capability in Capability:
        assert entitlements.includes(capability)


def test_entitlements_do_not_contain_pricing():
    entitlements = BusinessEntitlements(
        business_id="business-1",
        capabilities=frozenset({
            Capability.CONVERSATION,
        }),
    )

    assert not hasattr(entitlements, "price")
    assert not hasattr(entitlements, "monthly_price")
    assert not hasattr(entitlements, "setup_fee")
