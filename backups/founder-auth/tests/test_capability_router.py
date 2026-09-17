import pytest

from app.assistant.capability import (
    Capability,
    CapabilityRequest,
    CapabilityResult,
)
from app.assistant.capability_router import CapabilityRouter


def make_request(
    capability: Capability = Capability.CONVERSATION,
) -> CapabilityRequest:
    return CapabilityRequest(
        capability=capability,
        business_id="business-001",
        reason="Handle the owner's request.",
    )


def test_router_routes_to_registered_handler():
    calls = []

    def handler(request):
        calls.append(request)
        return CapabilityResult(
            capability=request.capability,
            business_id=request.business_id,
            success=True,
            message="Handled.",
        )

    router = CapabilityRouter(
        {
            Capability.CONVERSATION: handler,
        }
    )

    request = make_request()

    result = router.route(request)

    assert result.capability is Capability.CONVERSATION
    assert result.business_id == "business-001"
    assert result.success is True
    assert result.message == "Handled."
    assert calls == [request]


def test_router_supports_registered_capability():
    router = CapabilityRouter(
        {
            Capability.RESEARCH: lambda request: CapabilityResult(
                capability=request.capability,
                business_id=request.business_id,
                success=True,
                message="Researched.",
            ),
        }
    )

    assert router.supports(Capability.RESEARCH) is True


def test_router_reports_unsupported_capability():
    router = CapabilityRouter(
        {
            Capability.RESEARCH: lambda request: CapabilityResult(
                capability=request.capability,
                business_id=request.business_id,
                success=True,
                message="Researched.",
            ),
        }
    )

    assert router.supports(Capability.TIME) is False


def test_router_rejects_unregistered_capability():
    router = CapabilityRouter(
        {
            Capability.RESEARCH: lambda request: CapabilityResult(
                capability=request.capability,
                business_id=request.business_id,
                success=True,
                message="Researched.",
            ),
        }
    )

    with pytest.raises(LookupError, match="No handler"):
        router.route(make_request(Capability.TIME))


def test_router_rejects_non_request():
    router = CapabilityRouter(
        {
            Capability.CONVERSATION: lambda request: CapabilityResult(
                capability=request.capability,
                business_id=request.business_id,
                success=True,
                message="Handled.",
            ),
        }
    )

    with pytest.raises(TypeError, match="CapabilityRequest"):
        router.route(object())


@pytest.mark.parametrize(
    "handlers",
    [None, [], "handlers"],
)
def test_router_rejects_invalid_handlers(handlers):
    with pytest.raises(TypeError, match="handlers"):
        CapabilityRouter(handlers)


def test_router_rejects_invalid_handler_key():
    with pytest.raises(TypeError, match="Capability"):
        CapabilityRouter(
            {
                "research": lambda request: CapabilityResult(
                    capability=Capability.RESEARCH,
                    business_id=request.business_id,
                    success=True,
                    message="Handled.",
                ),
            }
        )


def test_router_rejects_non_callable_handler():
    with pytest.raises(TypeError, match="callable"):
        CapabilityRouter(
            {
                Capability.RESEARCH: "not callable",
            }
        )


def test_router_does_not_call_handler_for_unsupported_capability():
    calls = []

    def handler(request):
        calls.append(request)
        return CapabilityResult(
            capability=request.capability,
            business_id=request.business_id,
            success=True,
            message="Handled.",
        )

    router = CapabilityRouter(
        {
            Capability.RESEARCH: handler,
        }
    )

    with pytest.raises(LookupError):
        router.route(make_request(Capability.TIME))

    assert calls == []


def test_router_can_register_multiple_capabilities():
    calls = []

    def research_handler(request):
        calls.append(("research", request))
        return CapabilityResult(
            capability=request.capability,
            business_id=request.business_id,
            success=True,
            message="Research result.",
        )

    def communication_handler(request):
        calls.append(("communication", request))
        return CapabilityResult(
            capability=request.capability,
            business_id=request.business_id,
            success=True,
            message="Communication result.",
        )

    router = CapabilityRouter(
        {
            Capability.RESEARCH: research_handler,
            Capability.COMMUNICATION: communication_handler,
        }
    )

    research_result = router.route(
        make_request(Capability.RESEARCH)
    )

    communication_result = router.route(
        make_request(Capability.COMMUNICATION)
    )

    assert research_result.message == "Research result."
    assert communication_result.message == "Communication result."
    assert len(calls) == 2


def test_router_rejects_handler_returning_arbitrary_object():
    router = CapabilityRouter(
        {
            Capability.CONVERSATION: lambda request: "not-a-result",
        }
    )

    with pytest.raises(
        TypeError,
        match="CapabilityResult",
    ):
        router.route(make_request())


def test_router_rejects_result_for_wrong_capability():
    router = CapabilityRouter(
        {
            Capability.RESEARCH: lambda request: CapabilityResult(
                capability=Capability.CONVERSATION,
                business_id=request.business_id,
                success=True,
                message="Wrong capability.",
            ),
        }
    )

    with pytest.raises(
        ValueError,
        match="capability",
    ):
        router.route(make_request(Capability.RESEARCH))


def test_router_rejects_result_for_wrong_business():
    router = CapabilityRouter(
        {
            Capability.RESEARCH: lambda request: CapabilityResult(
                capability=request.capability,
                business_id="business-999",
                success=True,
                message="Wrong business.",
            ),
        }
    )

    with pytest.raises(
        ValueError,
        match="business",
    ):
        router.route(make_request(Capability.RESEARCH))


def test_router_returns_valid_capability_result():
    router = CapabilityRouter(
        {
            Capability.RESEARCH: lambda request: CapabilityResult(
                capability=request.capability,
                business_id=request.business_id,
                success=True,
                message="Research completed.",
            ),
        }
    )

    result = router.route(make_request(Capability.RESEARCH))

    assert isinstance(result, CapabilityResult)
    assert result.capability is Capability.RESEARCH
    assert result.business_id == "business-001"
    assert result.success is True
    assert result.message == "Research completed."
