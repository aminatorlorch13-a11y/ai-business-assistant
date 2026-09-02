import pytest

from app.assistant.capability import (
    Capability,
    CapabilityRequest,
    CapabilityResult,
)
from app.assistant.capability_router import CapabilityRouter
from app.trust.capability_executor import CapabilityExecutor
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


def make_router(calls: list | None = None) -> CapabilityRouter:
    if calls is None:
        calls = []

    def handler(request):
        calls.append(request)
        return CapabilityResult(
            capability=request.capability,
            business_id=request.business_id,
            success=True,
            message="Capability completed.",
        )

    return CapabilityRouter(
        {
            Capability.CONVERSATION: handler,
            Capability.RESEARCH: handler,
        }
    )


def test_executor_authorizes_before_routing():
    calls = []

    executor = CapabilityExecutor(
        policy=make_policy(
            frozenset({Capability.CONVERSATION})
        ),
        router=make_router(calls),
    )

    result = executor.execute(
        make_request(Capability.CONVERSATION)
    )

    assert isinstance(result, CapabilityResult)
    assert result.capability is Capability.CONVERSATION
    assert result.business_id == "business-001"
    assert result.success is True
    assert calls == [
        make_request(Capability.CONVERSATION)
    ]


def test_executor_denies_unauthorized_capability():
    calls = []

    executor = CapabilityExecutor(
        policy=make_policy(
            frozenset({Capability.CONVERSATION})
        ),
        router=make_router(calls),
    )

    with pytest.raises(
        PermissionError,
        match="not permitted",
    ):
        executor.execute(
            make_request(Capability.RESEARCH)
        )

    assert calls == []


def test_denied_capability_never_reaches_handler():
    calls = []

    executor = CapabilityExecutor(
        policy=make_policy(frozenset()),
        router=make_router(calls),
    )

    with pytest.raises(PermissionError):
        executor.execute(
            make_request(Capability.CONVERSATION)
        )

    assert calls == []


def test_cross_business_request_is_denied_before_routing():
    calls = []

    executor = CapabilityExecutor(
        policy=make_policy(
            frozenset({Capability.CONVERSATION})
        ),
        router=make_router(calls),
    )

    with pytest.raises(PermissionError):
        executor.execute(
            make_request(
                capability=Capability.CONVERSATION,
                business_id="business-999",
            )
        )

    assert calls == []


@pytest.mark.parametrize(
    "request_value",
    [None, "request", object()],
)
def test_executor_rejects_invalid_request(request_value):
    executor = CapabilityExecutor(
        policy=make_policy(),
        router=make_router(),
    )

    with pytest.raises(
        TypeError,
        match="CapabilityRequest",
    ):
        executor.execute(request_value)


@pytest.mark.parametrize(
    "policy_value",
    [None, object()],
)
def test_executor_rejects_invalid_policy(policy_value):
    with pytest.raises(
        TypeError,
        match="CapabilityPolicy",
    ):
        CapabilityExecutor(
            policy=policy_value,
            router=make_router(),
        )


@pytest.mark.parametrize(
    "router_value",
    [None, object()],
)
def test_executor_rejects_invalid_router(router_value):
    with pytest.raises(
        TypeError,
        match="CapabilityRouter",
    ):
        CapabilityExecutor(
            policy=make_policy(),
            router=router_value,
        )


def test_executor_supports_full_current_capability_policy():
    calls = []

    router = CapabilityRouter(
        {
            capability: (
                lambda request, _calls=calls: (
                    _calls.append(request),
                    CapabilityResult(
                        capability=request.capability,
                        business_id=request.business_id,
                        success=True,
                        message="Capability completed.",
                    ),
                )[1]
            )
            for capability in Capability
        }
    )

    executor = CapabilityExecutor(
        policy=make_policy(frozenset(Capability)),
        router=router,
    )

    for capability in Capability:
        result = executor.execute(
            make_request(capability)
        )

        assert isinstance(result, CapabilityResult)
        assert result.capability is capability
        assert result.business_id == "business-001"

    assert len(calls) == len(Capability)
