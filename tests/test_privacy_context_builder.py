from app.ai.context import AIContext
from app.ai.privacy_context import PrivacyContext
from app.ai.privacy_context_builder import PrivacyContextBuilder
from app.assistant.conversation import (
    ConversationHistory,
    ConversationRole,
    ConversationTurn,
)
from app.memory.context import MemoryContext


def make_context(contents: list[tuple[ConversationRole, str]]) -> AIContext:
    business_id = "business-001"
    history = ConversationHistory(
        business_id=business_id,
        turns=tuple(
            ConversationTurn(
                business_id=business_id,
                role=role,
                content=content,
            )
            for role, content in contents
        ),
    )
    return AIContext(
        memory_context=MemoryContext(business_id=business_id, memories=()),
        conversation_history=history,
    )


def test_builder_preserves_chronological_order_when_history_fits():
    context = make_context([
        (ConversationRole.USER, "First question"),
        (ConversationRole.ASSISTANT, "First answer"),
        (ConversationRole.USER, "Latest question"),
    ])

    result = PrivacyContextBuilder().build(context)

    assert result.conversation_text.index("First question") < (
        result.conversation_text.index("First answer")
    ) < result.conversation_text.index("Latest question")
    assert "[earlier conversation context omitted" not in result.conversation_text


def test_builder_preserves_newest_turns_when_history_exceeds_limit():
    builder = PrivacyContextBuilder()
    builder.MAX_CONVERSATION_CHARS = 240

    context = make_context([
        (ConversationRole.USER, "old-" + "A" * 100),
        (ConversationRole.ASSISTANT, "middle-" + "B" * 100),
        (ConversationRole.USER, "latest-question-keep-this"),
        (ConversationRole.ASSISTANT, "latest-answer-keep-this"),
    ])

    result = builder.build(context)
    rendered = result.conversation_text

    assert len(rendered) <= builder.MAX_CONVERSATION_CHARS
    assert builder._OMISSION_MARKER in rendered
    assert "latest-question-keep-this" in rendered
    assert "latest-answer-keep-this" in rendered
    assert "old-" not in rendered
    assert rendered.index("latest-question-keep-this") < (
        rendered.index("latest-answer-keep-this")
    )


def test_builder_explicitly_marks_oversized_newest_turn():
    builder = PrivacyContextBuilder()
    builder.MAX_CONVERSATION_CHARS = 180

    context = make_context([
        (ConversationRole.USER, "older context"),
        (ConversationRole.ASSISTANT, "X" * 500 + "important-ending"),
    ])

    result = builder.build(context)
    rendered = result.conversation_text

    assert len(rendered) <= builder.MAX_CONVERSATION_CHARS
    assert builder._OMISSION_MARKER in rendered
    assert builder._OVERSIZED_TURN_MARKER in rendered
    assert "important-ending" in rendered
    assert "older context" not in rendered


def test_builder_does_not_mutate_or_delete_durable_history():
    context = make_context([
        (ConversationRole.USER, "old-" + "A" * 100),
        (ConversationRole.ASSISTANT, "middle-" + "B" * 100),
        (ConversationRole.USER, "latest"),
    ])
    original_turns = context.conversation_history.turns

    builder = PrivacyContextBuilder()
    builder.MAX_CONVERSATION_CHARS = 180
    builder.build(context)

    assert context.conversation_history.turns == original_turns
    assert len(context.conversation_history.turns) == 3


def test_builder_rejects_invalid_context():
    import pytest

    with pytest.raises(TypeError, match="AIContext"):
        PrivacyContextBuilder().build(object())
