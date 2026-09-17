import pytest

from app.assistant.action import AssistantAction
from app.assistant.intent import AssistantIntent
from app.assistant.interpretation import AIInterpretation
from app.assistant.message import AssistantMessage
from app.assistant.interpretation_validator import AIInterpretationValidator


def make_valid_interpretation() -> AIInterpretation:
    return AIInterpretation(
        intent=AssistantIntent(
            business_id="business-001",
            intent_type="business_task",
            instruction="Create an appointment.",
        ),
        action=AssistantAction(
            business_id="business-001",
            action_type="create",
            target="appointment",
            instruction="Create an appointment.",
        ),
    )


def test_validator_accepts_valid_interpretation():
    validator = AIInterpretationValidator()

    interpretation = make_valid_interpretation()

    result = validator.validate(
        interpretation,
        business_id="business-001",
    )

    assert result == interpretation


def test_validator_rejects_wrong_business():
    validator = AIInterpretationValidator()

    with pytest.raises(ValueError):
        validator.validate(
            make_valid_interpretation(),
            business_id="business-999",
        )


def test_validator_rejects_mismatched_message_business():
    validator = AIInterpretationValidator()

    interpretation = AIInterpretation(
        intent=AssistantIntent(
            business_id="business-999",
            intent_type="business_task",
            instruction="Create an appointment.",
        ),
        action=AssistantAction(
            business_id="business-999",
            action_type="create",
            target="appointment",
            instruction="Create an appointment.",
        ),
    )

    with pytest.raises(ValueError):
        validator.validate(
            interpretation,
            business_id="business-001",
        )


def make_interpretation(
    intent_type: str,
    action_type: str,
) -> AIInterpretation:
    return AIInterpretation(
        intent=AssistantIntent(
            business_id="business-001",
            intent_type=intent_type,
            instruction="Handle the request.",
        ),
        action=AssistantAction(
            business_id="business-001",
            action_type=action_type,
            target="appointment",
            instruction="Handle the request.",
        ),
    )


def test_validator_accepts_business_task_with_create():
    validator = AIInterpretationValidator()

    interpretation = make_interpretation(
        "business_task",
        "create",
    )

    assert validator.validate(
        interpretation,
        business_id="business-001",
    ) == interpretation


def test_validator_accepts_business_task_with_update():
    validator = AIInterpretationValidator()

    interpretation = make_interpretation(
        "business_task",
        "update",
    )

    assert validator.validate(
        interpretation,
        business_id="business-001",
    ) == interpretation


def test_validator_accepts_general_question_with_none_action():
    validator = AIInterpretationValidator()

    interpretation = make_interpretation(
        "general_question",
        "none",
    )

    assert validator.validate(
        interpretation,
        business_id="business-001",
    ) == interpretation


def test_validator_rejects_general_question_with_create():
    validator = AIInterpretationValidator()

    interpretation = make_interpretation(
        "general_question",
        "create",
    )

    with pytest.raises(ValueError):
        validator.validate(
            interpretation,
            business_id="business-001",
        )


def test_validator_rejects_general_question_with_delete():
    validator = AIInterpretationValidator()

    interpretation = make_interpretation(
        "general_question",
        "delete",
    )

    with pytest.raises(ValueError):
        validator.validate(
            interpretation,
            business_id="business-001",
        )

def test_validator_rejects_empty_or_invalid_business_id():
    validator = AIInterpretationValidator()
    interpretation = make_interpretation(
        "business_task",
        "create",
    )

    with pytest.raises(ValueError):
        validator.validate(
            interpretation,
            business_id="",
        )


def test_validator_rejects_action_with_unexpected_target():
    validator = AIInterpretationValidator()

    interpretation = AIInterpretation(
        intent=AssistantIntent(
            business_id="business-001",
            intent_type="business_task",
            instruction="Create an appointment.",
        ),
        action=AssistantAction(
            business_id="business-001",
            action_type="create",
            target="invoice",
            instruction="Create an appointment.",
        ),
    )

    with pytest.raises(ValueError):
        validator.validate(
            interpretation,
            business_id="business-001",
        )

def test_validator_rejects_unknown_intent_without_key_error():
    validator = AIInterpretationValidator()

    interpretation = AIInterpretation(
        intent=AssistantIntent(
            business_id="business-001",
            intent_type="general_question",
            instruction="Answer the customer.",
        ),
        action=AssistantAction(
            business_id="business-001",
            action_type="none",
            target="assistant",
            instruction="No action required.",
        ),
    )

    object.__setattr__(
        interpretation.intent,
        "intent_type",
        "future_unknown_intent",
    )

    with pytest.raises(ValueError, match="Unknown intent"):
        validator.validate(
            interpretation,
            business_id="business-001",
        )


def test_validator_rejects_non_interpretation():
    validator = AIInterpretationValidator()

    with pytest.raises(TypeError, match="AIInterpretation"):
        validator.validate(
            object(),
            "business-001",
        )


def test_validator_rejects_non_string_business_id():
    validator = AIInterpretationValidator()

    interpretation = make_interpretation("business_task", "create")

    with pytest.raises(ValueError, match="business_id"):
        validator.validate(
            interpretation,
            123,
        )


def test_validator_rejects_oversized_business_id():
    validator = AIInterpretationValidator()

    interpretation = make_interpretation("business_task", "create")

    with pytest.raises(ValueError, match="maximum"):
        validator.validate(
            interpretation,
            "x" * 129,
        )
