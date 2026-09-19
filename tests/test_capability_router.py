import pytest

from app.assistant.capability import Capability
from app.assistant.capability_router import CapabilityRouter
from app.assistant.execution import (
    CapabilityExecutionRequest,
    CapabilityExecutionResult,
)


def make_request(
    capability: Capability = Capability.CONVERSATION,
    operation: str = "respond",
    business_id: str = "business-001",
) -> CapabilityExecutionRequest:
    return CapabilityExecutionRequest(
        capability=capability,
        operation=operation,
        business_id=business_id,
        arguments={"input": "test"},
        reason="Handle the owner's request.",
    )


def make_result(
    request: CapabilityExecutionRequest,
    *,
    success: bool = True,
    business_id: str | None = None,
) -> CapabilityExecutionResult:
    return CapabilityExecutionResult(
        success=success,
        capability=request.capability,
        operation=request.operation,
        business_id=(
            request.business_id
            if business_id is None
            else business_id
        ),
        data={"message": "Handled."},
        error=None if success else "Operation failed.",
    )


def test_router_routes_to_registered_operation():
    calls = []

    def handler(request):
        calls.append(request)
        return make_result(request)

    router = CapabilityRouter(
        {
            Capability.CONVERSATION: {
                "respond": handler,
            },
        }
    )

    request = make_request()
    result = router.route(request)

    assert result.capability is Capability.CONVERSATION
    assert result.operation == "respond"
    assert result.business_id == "business-001"
    assert result.success is True
    assert calls == [request]


def test_router_supports_registered_capability():
    router = CapabilityRouter(
        {
            Capability.RESEARCH: {
                "search": lambda request: make_result(request),
            },
        }
    )

    assert router.supports(Capability.RESEARCH) is True


def test_router_reports_unsupported_capability():
    router = CapabilityRouter(
        {
            Capability.RESEARCH: {
                "search": lambda request: make_result(request),
            },
        }
    )

    assert router.supports(Capability.TIME) is False


def test_router_supports_registered_operation():
    router = CapabilityRouter(
        {
            Capability.RESEARCH: {
                "search": lambda request: make_result(request),
            },
        }
    )

    assert router.supports_operation(
        Capability.RESEARCH,
        "search",
    ) is True


def test_router_reports_unsupported_operation():
    router = CapabilityRouter(
        {
            Capability.RESEARCH: {
                "search": lambda request: make_result(request),
            },
        }
    )

    assert router.supports_operation(
        Capability.RESEARCH,
        "delete",
    ) is False


def test_router_rejects_unregistered_capability():
    router = CapabilityRouter(
        {
            Capability.RESEARCH: {
                "search": lambda request: make_result(request),
            },
        }
    )

    with pytest.raises(LookupError, match="capability"):
        router.route(make_request(Capability.TIME, "get_time"))


def test_router_rejects_unregistered_operation():
    router = CapabilityRouter(
        {
            Capability.RESEARCH: {
                "search": lambda request: make_result(request),
            },
        }
    )

    with pytest.raises(LookupError, match="operation"):
        router.route(
            make_request(
                Capability.RESEARCH,
                "unknown",
            )
        )


def test_router_rejects_non_request():
    router = CapabilityRouter(
        {
            Capability.CONVERSATION: {
                "respond": lambda request: make_result(request),
            },
        }
    )

    with pytest.raises(
        TypeError,
        match="CapabilityExecutionRequest",
    ):
        router.route(object())


@pytest.mark.parametrize(
    "handlers",
    [None, [], "handlers"],
)
def test_router_rejects_invalid_handlers(handlers):
    with pytest.raises(TypeError, match="handlers"):
        CapabilityRouter(handlers)


def test_router_rejects_invalid_capability_key():
    with pytest.raises(TypeError, match="Capability"):
        CapabilityRouter(
            {
                "research": {
                    "search": lambda request: make_result(request),
                },
            }
        )


def test_router_rejects_invalid_operations_mapping():
    with pytest.raises(TypeError, match="operations"):
        CapabilityRouter(
            {
                Capability.RESEARCH: "not a mapping",
            }
        )


def test_router_rejects_invalid_operation_name():
    with pytest.raises(TypeError, match="operation"):
        CapabilityRouter(
            {
                Capability.RESEARCH: {
                    123: lambda request: make_result(request),
                },
            }
        )


def test_router_rejects_empty_operation_name():
    with pytest.raises(ValueError, match="non-empty"):
        CapabilityRouter(
            {
                Capability.RESEARCH: {
                    "   ": lambda request: make_result(request),
                },
            }
        )


def test_router_rejects_non_callable_handler():
    with pytest.raises(TypeError, match="callable"):
        CapabilityRouter(
            {
                Capability.RESEARCH: {
                    "search": "not callable",
                },
            }
        )


def test_router_does_not_call_handler_for_unsupported_capability():
    calls = []

    def handler(request):
        calls.append(request)
        return make_result(request)

    router = CapabilityRouter(
        {
            Capability.RESEARCH: {
                "search": handler,
            },
        }
    )

    with pytest.raises(LookupError):
        router.route(
            make_request(
                Capability.TIME,
                "get_time",
            )
        )

    assert calls == []


def test_router_does_not_call_handler_for_unsupported_operation():
    calls = []

    def handler(request):
        calls.append(request)
        return make_result(request)

    router = CapabilityRouter(
        {
            Capability.RESEARCH: {
                "search": handler,
            },
        }
    )

    with pytest.raises(LookupError):
        router.route(
            make_request(
                Capability.RESEARCH,
                "delete",
            )
        )

    assert calls == []


def test_router_can_register_multiple_operations():
    calls = []

    def search_handler(request):
        calls.append(("search", request))
        return make_result(request)

    def summarize_handler(request):
        calls.append(("summarize", request))
        return make_result(request)

    router = CapabilityRouter(
        {
            Capability.RESEARCH: {
                "search": search_handler,
                "summarize": summarize_handler,
            },
        }
    )

    search_result = router.route(
        make_request(Capability.RESEARCH, "search")
    )
    summarize_result = router.route(
        make_request(Capability.RESEARCH, "summarize")
    )

    assert search_result.operation == "search"
    assert summarize_result.operation == "summarize"
    assert len(calls) == 2


def test_router_can_register_multiple_capabilities():
    router = CapabilityRouter(
        {
            Capability.RESEARCH: {
                "search": lambda request: make_result(request),
            },
            Capability.COMMUNICATION: {
                "send": lambda request: make_result(request),
            },
        }
    )

    research_result = router.route(
        make_request(Capability.RESEARCH, "search")
    )
    communication_result = router.route(
        make_request(Capability.COMMUNICATION, "send")
    )

    assert research_result.capability is Capability.RESEARCH
    assert communication_result.capability is Capability.COMMUNICATION


def test_router_rejects_handler_returning_arbitrary_object():
    router = CapabilityRouter(
        {
            Capability.CONVERSATION: {
                "respond": lambda request: "not-a-result",
            },
        }
    )

    with pytest.raises(
        TypeError,
        match="CapabilityExecutionResult",
    ):
        router.route(make_request())


def test_router_rejects_result_for_wrong_capability():
    def handler(request):
        return CapabilityExecutionResult(
            success=True,
            capability=Capability.RESEARCH,
            operation=request.operation,
            business_id=request.business_id,
        )

    router = CapabilityRouter(
        {
            Capability.CONVERSATION: {
                "respond": handler,
            },
        }
    )

    with pytest.raises(ValueError, match="capability"):
        router.route(make_request())


def test_router_rejects_result_for_wrong_operation():
    def handler(request):
        return CapabilityExecutionResult(
            success=True,
            capability=request.capability,
            operation="different_operation",
            business_id=request.business_id,
        )

    router = CapabilityRouter(
        {
            Capability.CONVERSATION: {
                "respond": handler,
            },
        }
    )

    with pytest.raises(ValueError, match="operation"):
        router.route(make_request())


def test_router_rejects_result_for_wrong_business():
    def handler(request):
        return make_result(
            request,
            business_id="business-999",
        )

    router = CapabilityRouter(
        {
            Capability.RESEARCH: {
                "search": handler,
            },
        }
    )

    with pytest.raises(ValueError, match="business"):
        router.route(
            make_request(
                Capability.RESEARCH,
                "search",
            )
        )


def test_router_returns_valid_execution_result():
    router = CapabilityRouter(
        {
            Capability.RESEARCH: {
                "search": lambda request: CapabilityExecutionResult(
                    success=True,
                    capability=request.capability,
                    operation=request.operation,
                    business_id=request.business_id,
                    data={"result": "Research completed."},
                    verification="verified",
                ),
            },
        }
    )

    result = router.route(
        make_request(
            Capability.RESEARCH,
            "search",
        )
    )

    assert isinstance(result, CapabilityExecutionResult)
    assert result.capability is Capability.RESEARCH
    assert result.operation == "search"
    assert result.business_id == "business-001"
    assert result.success is True
    assert result.verification == "verified"
