import pytest

from app.ai.response_parser import AIResponseParser


BUSINESS_ID = "business-001"


def valid_response() -> dict[str, object]:
    return {
        "intent_type": "business_task",
        "instruction": "Create an appointment.",
        "action_type": "create",
        "target": "appointment",
        "action_instruction": "Create an appointment.",
    }


def test_parser_rejects_non_mapping_input():
    parser = AIResponseParser()

    with pytest.raises(ValueError, match="mapping"):
        parser.parse(
            ["business_task"],
            business_id=BUSINESS_ID,
        )


@pytest.mark.parametrize(
    "field",
    [
        "intent_type",
        "instruction",
        "action_type",
        "target",
        "action_instruction",
    ],
)
def test_parser_rejects_missing_required_field(field: str):
    parser = AIResponseParser()
    response = valid_response()
    response.pop(field)

    with pytest.raises(
        ValueError,
        match="missing required fields",
    ):
        parser.parse(
            response,
            business_id=BUSINESS_ID,
        )


@pytest.mark.parametrize(
    "field",
    [
        "intent_type",
        "instruction",
        "action_type",
        "target",
        "action_instruction",
    ],
)
def test_parser_rejects_empty_or_whitespace_required_field(field: str):
    parser = AIResponseParser()

    for value in ("", "   ", "\n\t"):
        response = valid_response()
        response[field] = value

        with pytest.raises(ValueError, match=field):
            parser.parse(
                response,
                business_id=BUSINESS_ID,
            )


@pytest.mark.parametrize(
    "field",
    [
        "intent_type",
        "instruction",
        "action_type",
        "target",
        "action_instruction",
    ],
)
def test_parser_rejects_non_string_required_field(field: str):
    parser = AIResponseParser()
    response = valid_response()
    response[field] = {"malicious": "payload"}

    with pytest.raises(
        ValueError,
        match=f"{field}.*string",
    ):
        parser.parse(
            response,
            business_id=BUSINESS_ID,
        )


@pytest.mark.parametrize(
    "intent_type",
    [
        "unknown",
        "delete_everything",
        "unknown_intent_value",
        "__admin__",
        "",
        "BUSINESS_TASK",
    ],
)
def test_parser_rejects_unknown_intent(intent_type: str):
    parser = AIResponseParser()
    response = valid_response()
    response["intent_type"] = intent_type

    with pytest.raises(
        ValueError,
        match="Unknown intent",
    ):
        parser.parse(
            response,
            business_id=BUSINESS_ID,
        )


@pytest.mark.parametrize(
    "action_type",
    [
        "hack",
        "execute",
        "__admin__",
        "",
        "CREATE",
    ],
)
def test_parser_rejects_unknown_action(action_type: str):
    parser = AIResponseParser()
    response = valid_response()
    response["action_type"] = action_type

    with pytest.raises(
        ValueError,
        match="Unknown action",
    ):
        parser.parse(
            response,
            business_id=BUSINESS_ID,
        )


def test_parser_rejects_forged_business_identity():
    parser = AIResponseParser()
    response = valid_response()
    response["business_id"] = "business-999"

    with pytest.raises(
        ValueError,
        match="does not belong",
    ):
        parser.parse(
            response,
            business_id=BUSINESS_ID,
        )


def test_parser_accepts_matching_business_identity():
    parser = AIResponseParser()
    response = valid_response()
    response["business_id"] = BUSINESS_ID

    result = parser.parse(
        response,
        business_id=BUSINESS_ID,
    )

    assert result.intent.business_id == BUSINESS_ID
    assert result.action.business_id == BUSINESS_ID


@pytest.mark.parametrize(
    "supplied_business_id",
    [
        None,
        "",
        "   ",
        123,
        [],
        {},
    ],
)
def test_parser_rejects_invalid_supplied_business_identity(
    supplied_business_id: object,
):
    parser = AIResponseParser()
    response = valid_response()

    # Explicitly supplying an invalid business_id is invalid AI output.
    response["business_id"] = supplied_business_id

    with pytest.raises(
        ValueError,
        match="business_id",
    ):
        parser.parse(
            response,
            business_id=BUSINESS_ID,
        )


def test_parser_accepts_response_without_business_id():
    parser = AIResponseParser()
    response = valid_response()

    result = parser.parse(
        response,
        business_id=BUSINESS_ID,
    )

    assert result.intent.business_id == BUSINESS_ID
    assert result.action.business_id == BUSINESS_ID


def test_parser_never_uses_ai_supplied_business_id_as_authority():
    parser = AIResponseParser()
    response = valid_response()

    response["business_id"] = "business-999"

    with pytest.raises(
        ValueError,
        match="does not belong",
    ):
        parser.parse(
            response,
            business_id="business-002",
        )


def test_parser_rejects_invalid_active_business_id():
    parser = AIResponseParser()

    with pytest.raises(
        ValueError,
        match="non-empty",
    ):
        parser.parse(
            valid_response(),
            business_id="",
        )


@pytest.mark.parametrize(
    "business_id",
    [
        "   ",
        "\n",
        "\t",
    ],
)
def test_parser_rejects_whitespace_only_active_business_id(
    business_id: str,
):
    parser = AIResponseParser()

    with pytest.raises(
        ValueError,
        match="non-empty",
    ):
        parser.parse(
            valid_response(),
            business_id=business_id,
        )


def test_parser_rejects_non_string_active_business_id():
    parser = AIResponseParser()

    with pytest.raises(
        ValueError,
        match="business_id must be a string",
    ):
        parser.parse(
            valid_response(),
            business_id=123,  # type: ignore[arg-type]
        )
