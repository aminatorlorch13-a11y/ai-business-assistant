import pytest

from app.ai.response_parser import AIResponseParser


def test_parser_parses_valid_business_task():
    parser = AIResponseParser()

    result = parser.parse(
        {
            "intent_type": "business_task",
            "instruction": "Create an appointment.",
            "action_type": "create",
            "target": "appointment",
            "action_instruction": "Create an appointment.",
        },
        business_id="business-001",
    )

    assert result.intent.intent_type == "business_task"
    assert result.intent.business_id == "business-001"
    assert result.action.action_type == "create"
    assert result.action.target == "appointment"
    assert result.action.business_id == "business-001"


def test_parser_rejects_missing_field():
    parser = AIResponseParser()

    with pytest.raises(ValueError):
        parser.parse(
            {
                "intent_type": "business_task",
                "instruction": "Create an appointment.",
                "action_type": "create",
            },
            business_id="business-001",
        )


def test_parser_rejects_unknown_intent():
    parser = AIResponseParser()

    with pytest.raises(ValueError):
        parser.parse(
            {
                "intent_type": "something_unknown",
                "instruction": "Do something.",
                "action_type": "none",
                "target": "assistant",
                "action_instruction": "No action.",
            },
            business_id="business-001",
        )


def test_parser_rejects_unknown_action():
    parser = AIResponseParser()

    with pytest.raises(ValueError):
        parser.parse(
            {
                "intent_type": "business_task",
                "instruction": "Do something.",
                "action_type": "hack",
                "target": "assistant",
                "action_instruction": "Do something.",
            },
            business_id="business-001",
        )


def test_parser_rejects_wrong_business_id():
    parser = AIResponseParser()

    with pytest.raises(ValueError):
        parser.parse(
            {
                "business_id": "business-999",
                "intent_type": "business_task",
                "instruction": "Create an appointment.",
                "action_type": "create",
                "target": "appointment",
                "action_instruction": "Create an appointment.",
            },
            business_id="business-001",
        )


def test_parser_rejects_empty_required_string():
    parser = AIResponseParser()

    with pytest.raises(ValueError):
        parser.parse(
            {
                "intent_type": "business_task",
                "instruction": "",
                "action_type": "create",
                "target": "appointment",
                "action_instruction": "Create an appointment.",
            },
            business_id="business-001",
        )


def test_parser_rejects_non_string_intent_type():
    parser = AIResponseParser()

    with pytest.raises(ValueError):
        parser.parse(
            {
                "intent_type": 123,
                "instruction": "Create an appointment.",
                "action_type": "create",
                "target": "appointment",
                "action_instruction": "Create an appointment.",
            },
            business_id="business-001",
        )


def test_parser_accepts_extra_metadata():
    parser = AIResponseParser()

    result = parser.parse(
        {
            "intent_type": "business_task",
            "instruction": "Create an appointment.",
            "action_type": "create",
            "target": "appointment",
            "action_instruction": "Create an appointment.",
            "confidence": 0.98,
            "reasoning": "Customer explicitly requested an appointment.",
        },
        business_id="business-001",
    )

    assert result.action.target == "appointment"


def test_parser_rejects_empty_business_id():
    parser = AIResponseParser()

    with pytest.raises(ValueError):
        parser.parse(
            {
                "intent_type": "business_task",
                "instruction": "Create an appointment.",
                "action_type": "create",
                "target": "appointment",
                "action_instruction": "Create an appointment.",
            },
            business_id="",
        )

def test_parser_rejects_non_string_instruction():
    parser = AIResponseParser()

    with pytest.raises(ValueError):
        parser.parse(
            {
                "intent_type": "business_task",
                "instruction": 123,
                "action_type": "create",
                "target": "appointment",
                "action_instruction": "Create an appointment.",
            },
            business_id="business-001",
        )


def test_parser_rejects_non_string_action_type():
    parser = AIResponseParser()

    with pytest.raises(ValueError):
        parser.parse(
            {
                "intent_type": "business_task",
                "instruction": "Create an appointment.",
                "action_type": 123,
                "target": "appointment",
                "action_instruction": "Create an appointment.",
            },
            business_id="business-001",
        )


def test_parser_rejects_non_string_target():
    parser = AIResponseParser()

    with pytest.raises(ValueError):
        parser.parse(
            {
                "intent_type": "business_task",
                "instruction": "Create an appointment.",
                "action_type": "create",
                "target": 123,
                "action_instruction": "Create an appointment.",
            },
            business_id="business-001",
        )


def test_parser_rejects_non_string_action_instruction():
    parser = AIResponseParser()

    with pytest.raises(ValueError):
        parser.parse(
            {
                "intent_type": "business_task",
                "instruction": "Create an appointment.",
                "action_type": "create",
                "target": "appointment",
                "action_instruction": 123,
            },
            business_id="business-001",
        )


def test_parser_rejects_none_values():
    parser = AIResponseParser()

    with pytest.raises(ValueError):
        parser.parse(
            {
                "intent_type": "business_task",
                "instruction": None,
                "action_type": "create",
                "target": "appointment",
                "action_instruction": "Create an appointment.",
            },
            business_id="business-001",
        )


def test_parser_rejects_non_string_business_id():
    parser = AIResponseParser()

    with pytest.raises(ValueError):
        parser.parse(
            {
                "business_id": 123,
                "intent_type": "business_task",
                "instruction": "Create an appointment.",
                "action_type": "create",
                "target": "appointment",
                "action_instruction": "Create an appointment.",
            },
            business_id="business-001",
        )
