import pytest

from app.assistant.capability import (
    Capability,
    CapabilityRequest,
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
        return "handled"

    router = CapabilityRouter(
        {
            Capability.CONVERSATION: handler,
        }
    )

    request = make_request()

    result = router.route(request)

    assert result == "handled"
    assert calls == [request]


def test_router_supports_registered_capability():
    router = CapabilityRouter(
        {
            Capability.RESEARCH: lambda request: "researched",
        }
    )

    assert router.supports(Capability.RESEARCH) is True


def test_router_reports_unsupported_capability():
    router = CapabilityRouter(
        {
            Capability.RESEARCH: lambda request: "researched",
        }
    )

    assert router.supports(Capability.TIME) is False


def test_router_rejects_unregistered_capability():
    router = CapabilityRouter(
        {
            Capability.RESEARCH: lambda request: "researched",
        }
    )

    with pytest.raises(LookupError, match="No handler"):
        router.route(make_request(Capability.TIME))


def test_router_rejects_non_request():
    router = CapabilityRouter(
        {
            Capability.CONVERSATION: lambda request: "handled",
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
                "research": lambda request: "handled",
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
        return "handled"

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
        return "research-result"

    def communication_handler(request):
        calls.append(("communication", request))
        return "communication-result"

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

    assert research_result == "research-result"
    assert communication_result == "communication-result"
    assert len(calls) == 2
