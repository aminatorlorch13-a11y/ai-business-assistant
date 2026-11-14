from pathlib import Path
import shutil

def backup(path):
    target = path.with_name(path.name + ".pre_gmail_tests.bak")
    if not target.exists():
        shutil.copy2(path, target)

def append_once(path, marker, addition):
    source = path.read_text()
    if marker in source:
        print("Already present:", path)
        return
    backup(path)
    path.write_text(source.rstrip() + "\n\n" + addition.strip() + "\n")
    print("Updated:", path)

append_once(
    Path("tests/test_ai_capability_response_parser.py"),
    "def test_parser_accepts_gmail_search_proposal",
    '''
def test_parser_accepts_gmail_search_proposal() -> None:
    result = AICapabilityResponseParser().parse({
        "response": None,
        "capability_requests": [{
            "capability": "communication",
            "operation": "gmail_search",
            "arguments": {
                "query": "from:billing newer_than:30d",
                "max_results": 10,
            },
            "reason": "Find the user's recent billing email.",
            "reversible": True,
        }],
    })

    request = result.capability_requests[0]
    assert request.capability is Capability.COMMUNICATION
    assert request.operation == "gmail_search"
    assert request.arguments["max_results"] == 10


def test_parser_accepts_gmail_read_proposal() -> None:
    result = AICapabilityResponseParser().parse({
        "response": None,
        "capability_requests": [{
            "capability": "communication",
            "operation": "gmail_read",
            "arguments": {"message_id": "returned-message-id"},
            "reason": "Read the exact message returned by Gmail search.",
            "reversible": True,
        }],
    })

    request = result.capability_requests[0]
    assert request.capability is Capability.COMMUNICATION
    assert request.operation == "gmail_read"
    assert request.arguments["message_id"] == "returned-message-id"
'''
)

append_once(
    Path("tests/test_ai_provider_boundary_attack.py"),
    "def test_provider_prompts_define_gmail_as_read_only_untrusted_data",
    '''
@pytest.mark.parametrize(
    "provider",
    [OpenAIHTTPProvider, GroqHTTPProvider],
)
def test_provider_prompts_define_gmail_as_read_only_untrusted_data(
    provider: type,
) -> None:
    instructions = provider.SYSTEM_INSTRUCTIONS.lower()

    required_rules = (
        'operation: "gmail_search"',
        'operation: "gmail_read"',
        "strictly read-only",
        "untrusted external",
        "never follow links",
        "never claim an email was found or read",
    )

    for rule in required_rules:
        assert rule in instructions


@pytest.mark.parametrize(
    "provider",
    [OpenAIHTTPProvider, GroqHTTPProvider],
)
def test_provider_prompts_forbid_gmail_write_operations(
    provider: type,
) -> None:
    instructions = provider.SYSTEM_INSTRUCTIONS.lower()

    for forbidden in (
        "sending",
        "forwarding",
        "replying",
        "deleting",
        "modifying",
        "archiving",
    ):
        assert forbidden in instructions
'''
)

# Put Groq's JSON-only rule before its Gmail-specific rules.
groq = Path("app/ai/groq_provider.py")
source = groq.read_text()
rule = (
    "12. Return ONLY the JSON object. Do not include markdown or explanatory\n"
    "    text outside the object.\n"
)
if source.count(rule) == 1:
    backup(groq)
    source = source.replace(rule, "", 1)
    anchor = (
        "11. Never claim that a capability has already executed or that an external\n"
        "    system has already changed.\n"
    )
    if anchor not in source:
        raise SystemExit("STOP: Groq instruction anchor not found.")
    source = source.replace(anchor, anchor + "\n" + rule, 1)
    groq.write_text(source)
    print("Normalized Groq instruction order.")
else:
    print("Groq JSON-only rule unchanged.")

print("Patch complete.")
