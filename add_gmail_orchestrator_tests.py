from pathlib import Path
import shutil

path = Path("tests/test_assistant_orchestrator.py")
source = path.read_text()

marker = "def test_gmail_read_only_operations_preserve_authenticated_context"
if marker in source:
    print("Gmail orchestrator regression tests already exist.")
    raise SystemExit(0)

backup = path.with_name(path.name + ".pre_gmail_orchestrator.bak")
shutil.copy2(path, backup)

tests = r'''

@pytest.mark.parametrize(
    ("operation", "arguments"),
    [
        ("gmail_search", {"query": "from:example.com", "max_results": 5}),
        ("gmail_read", {"message_id": "gmail-message-001"}),
    ],
)
def test_gmail_read_only_operations_preserve_authenticated_context(
    tmp_path,
    operation,
    arguments,
):
    (
        processor,
        executor,
        _old_policy,
        confirmation_service,
        commercial_access,
        _database,
    ) = make_structured_stack(tmp_path)

    processor.process.return_value = AIResult(
        capability_requests=(
            AICapabilityRequest(
                capability=Capability.COMMUNICATION,
                operation=operation,
                arguments=arguments,
                reason="The user explicitly requested Gmail access.",
                reversible=True,
            ),
        )
    )

    executor.execute.return_value = CapabilityExecutionResult(
        success=True,
        capability=Capability.COMMUNICATION,
        operation=operation,
        business_id=BUSINESS_ID,
        data={"status": "Gmail operation completed."},
    )

    policy = CapabilityOperationPolicy(
        confirmation_by_operation={
            Capability.COMMUNICATION: {
                "gmail_search": False,
                "gmail_read": False,
            }
        }
    )

    orchestrator = make_orchestrator(
        processor,
        executor,
        policy,
        confirmation_service,
        commercial_access,
    )

    tenant = make_tenant()

    response = orchestrator.handle(
        AssistantMessage(
            business_id=BUSINESS_ID,
            content="Find my latest email.",
        ),
        tenant=tenant,
        channel="web",
        integration="gmail",
    )

    assert "Gmail operation completed." in response.message
    processor.process.assert_called_once()
    executor.execute.assert_called_once()
    executor.authorize.assert_not_called()

    execution_request = executor.execute.call_args.args[0]

    assert isinstance(execution_request, CapabilityExecutionRequest)
    assert execution_request.capability is Capability.COMMUNICATION
    assert execution_request.operation == operation
    assert execution_request.business_id == BUSINESS_ID
    assert execution_request.actor_user_id == tenant.principal.user_id
    assert execution_request.integration == "gmail"
    assert execution_request.channel == "web"
    assert dict(execution_request.arguments) == arguments
'''

path.write_text(source.rstrip() + "\n\n" + tests)
print(f"Added Gmail orchestrator tests to {path}")
print(f"Backup: {backup}")
