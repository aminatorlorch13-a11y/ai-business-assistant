from app.ai.context import AIContext
from app.ai.privacy_context import PrivacyContext
from app.ai.privacy_context_builder import PrivacyContextBuilder
from app.assistant.conversation import (
    ConversationHistory,
    ConversationRole,
    ConversationTurn,
)
from app.memory.context import MemoryContext


def make_context(
    contents: list[tuple[ConversationRole, str]],
    query: str | None = None,
) -> AIContext:
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
        query=query,
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


def test_builder_recovers_older_relevant_turns_and_keeps_recent_context():
    builder = PrivacyContextBuilder()
    builder.MAX_CONVERSATION_CHARS = 320

    context = make_context([
        (ConversationRole.USER, "Unrelated old discussion about gardening."),
        (
            ConversationRole.ASSISTANT,
            "The account reference is ORBIT-742 and belongs to the customer.",
        ),
        (
            ConversationRole.USER,
            "Another unrelated historical discussion about football.",
        ),
        (
            ConversationRole.USER,
            "What should we work on in the current session?",
        ),
        (
            ConversationRole.ASSISTANT,
            "We should review the current project tasks together.",
        ),
    ], query="What is the ORBIT-742 customer account reference?")

    rendered = builder.build(context).conversation_text

    assert len(rendered) <= builder.MAX_CONVERSATION_CHARS
    assert "ORBIT-742" in rendered
    assert "current session" in rendered
    assert "current project tasks" in rendered
    assert "gardening" not in rendered
    assert "football" not in rendered

    assert rendered.index("ORBIT-742") < (
        rendered.index("current session")
    ) < rendered.index("current project tasks")


def test_builder_keeps_recent_context_when_query_has_no_useful_terms():
    builder = PrivacyContextBuilder()
    builder.MAX_CONVERSATION_CHARS = 240

    context = make_context([
        (ConversationRole.USER, "Older discussion " + "A" * 100),
        (ConversationRole.ASSISTANT, "Recent answer to preserve"),
        (ConversationRole.USER, "Latest question to preserve"),
    ], query="What is it?")

    rendered = builder.build(context).conversation_text

    assert len(rendered) <= builder.MAX_CONVERSATION_CHARS
    assert "Recent answer to preserve" in rendered
    assert "Latest question to preserve" in rendered


def test_builder_does_not_duplicate_turns_during_retrieval():
    builder = PrivacyContextBuilder()
    builder.MAX_CONVERSATION_CHARS = 225

    context = make_context([
        (ConversationRole.USER, "ORBIT-742 customer account reference"),
        (ConversationRole.ASSISTANT, "The reference is ORBIT-742."),
        (ConversationRole.USER, "Recent unrelated question."),
        (ConversationRole.ASSISTANT, "Recent unrelated answer."),
    ], query="Find ORBIT-742 customer account reference")

    rendered = builder.build(context).conversation_text

    assert rendered.count("ORBIT-742 customer account reference") == 1
    assert rendered.count("Recent unrelated question.") == 1
    assert rendered.count("Recent unrelated answer.") == 1
