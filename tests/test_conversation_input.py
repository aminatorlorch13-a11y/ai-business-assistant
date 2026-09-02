import pytest

from app.voice.input import (
    ConversationInput,
    ConversationInputSource,
)


def test_voice_input_is_valid():
    value = ConversationInput(
        text="Hello assistant.",
        source=ConversationInputSource.VOICE,
    )

    assert value.text == "Hello assistant."
    assert value.source is ConversationInputSource.VOICE


def test_text_input_is_valid():
    value = ConversationInput(
        text="Show me today's schedule.",
        source=ConversationInputSource.TEXT,
    )

    assert value.text == "Show me today's schedule."
    assert value.source is ConversationInputSource.TEXT


def test_input_is_immutable():
    value = ConversationInput(
        text="Hello.",
        source=ConversationInputSource.TEXT,
    )

    with pytest.raises(AttributeError):
        value.text = "Changed."


@pytest.mark.parametrize("value", ["", " ", "\n\t"])
def test_input_rejects_blank_text(value):
    with pytest.raises(ValueError, match="non-empty"):
        ConversationInput(
            text=value,
            source=ConversationInputSource.TEXT,
        )


@pytest.mark.parametrize("value", [None, 123, object(), True])
def test_input_rejects_non_string_text(value):
    with pytest.raises(ValueError, match="non-empty"):
        ConversationInput(
            text=value,
            source=ConversationInputSource.TEXT,
        )


@pytest.mark.parametrize(
    "value",
    [None, "voice", "text", object(), True],
)
def test_input_rejects_invalid_source(value):
    with pytest.raises(TypeError, match="source"):
        ConversationInput(
            text="Hello.",
            source=value,
        )


def test_input_sources_are_distinct():
    assert ConversationInputSource.VOICE is not ConversationInputSource.TEXT


def test_input_source_values_are_stable():
    assert ConversationInputSource.VOICE.value == "voice"
    assert ConversationInputSource.TEXT.value == "text"


def test_input_preserves_text_content():
    original = "Please check order #A-42 and tell me what's happening."

    value = ConversationInput(
        text=original,
        source=ConversationInputSource.TEXT,
    )

    assert value.text == original
