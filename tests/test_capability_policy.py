import pytest

from app.assistant.capability import Capability, CapabilityRequest
from app.trust.capability_policy import CapabilityPolicy


def make_request(
    capability: Capability = Capability.CONVERSATION,
    business_id: str = "business-001",
) -> CapabilityRequest:
    return CapabilityRequest(
        capability=capability,
        business_id=business_id,
        reason="Handle the owner's request.",
    )


def make_policy(
    allowed_capabilities: frozenset[Capability] | None = None,
) -> CapabilityPolicy:
    if allowed_capabilities is None:
        allowed_capabilities = frozenset(
            {Capability.CONVERSATION}
        )

    return CapabilityPolicy(
        business_id="business-001",
        allowed_capabilities=allowed_capabilities,
    )


def test_policy_accepts_valid_configuration():
    policy = make_policy()

    assert policy.business_id == "business-001"
    assert policy.allowed_capabilities == frozenset(
        {Capability.CONVERSATION}
    )


def test_allowed_capability_is_authorized():
    policy = make_policy(
        frozenset({Capability.CONVERSATION, Capability.TIME})
    )

    assert policy.allows(make_request(Capability.CONVERSATION)) is True
    assert policy.allows(make_request(Capability.TIME)) is True


def test_unlisted_capability_is_denied():
    policy = make_policy(
        frozenset({Capability.CONVERSATION})
    )

    assert policy.allows(make_request(Capability.RESEARCH)) is False


def test_cross_business_request_is_denied():
    policy = make_policy(
        frozenset({Capability.CONVERSATION})
    )

    request = make_request(
        capability=Capability.CONVERSATION,
        business_id="business-002",
    )

    assert policy.allows(request) is False


def test_policy_is_immutable():
    policy = make_policy()

    with pytest.raises(AttributeError):
        policy.business_id = "business-002"

    with pytest.raises(AttributeError):
        policy.allowed_capabilities = frozenset()


def test_policy_requires_non_empty_business_id():
    with pytest.raises(ValueError, match="business_id"):
        CapabilityPolicy(
            business_id="",
            allowed_capabilities=frozenset(),
        )


@pytest.mark.parametrize(
    "business_id",
    [None, 123],
)
def test_policy_rejects_invalid_business_id(business_id):
    with pytest.raises(TypeError, match="business_id"):
        CapabilityPolicy(
            business_id=business_id,
            allowed_capabilities=frozenset(),
        )


def test_policy_requires_frozenset():
    with pytest.raises(TypeError, match="frozenset"):
        CapabilityPolicy(
            business_id="business-001",
            allowed_capabilities={Capability.CONVERSATION},
        )


def test_policy_rejects_invalid_capability_members():
    with pytest.raises(
        TypeError,
        match="Capability values",
    ):
        CapabilityPolicy(
            business_id="business-001",
            allowed_capabilities=frozenset(
                {Capability.CONVERSATION, "research"}
            ),
        )


@pytest.mark.parametrize(
    "invalid_request",
    [None, "request", 123],
)
def test_policy_rejects_invalid_request(invalid_request):
    policy = make_policy()

    with pytest.raises(TypeError, match="request"):
        policy.allows(invalid_request)


def test_full_capability_policy_can_authorize_all_current_capabilities():
    all_capabilities = frozenset(Capability)

    policy = make_policy(all_capabilities)

    for capability in Capability:
        assert policy.allows(
            make_request(capability)
        ) is True


def test_empty_policy_denies_every_current_capability():
    policy = make_policy(frozenset())

    for capability in Capability:
        assert policy.allows(
            make_request(capability)
        ) is False
