import pytest

from app.assistant.conversation import (
    ConversationHistory,
    ConversationRole,
    ConversationTurn,
)


def test_empty_history_is_valid():
    history = ConversationHistory(business_id="business-1")

    assert history.business_id == "business-1"
    assert history.turns == ()
    assert history.is_empty is True
    assert history.max_turns is None


def test_append_returns_new_history_and_preserves_order():
    history = ConversationHistory(business_id="business-1")

    user_turn = ConversationTurn(
        business_id="business-1",
        role=ConversationRole.USER,
        content="Hello",
    )
    assistant_turn = ConversationTurn(
        business_id="business-1",
        role=ConversationRole.ASSISTANT,
        content="Hello. How can I help?",
    )

    first = history.append(user_turn)
    second = first.append(assistant_turn)

    assert history.turns == ()
    assert first.turns == (user_turn,)
    assert second.turns == (user_turn, assistant_turn)
    assert second.is_empty is False


def test_history_is_bounded_to_max_turns():
    history = ConversationHistory(
        business_id="business-1",
        max_turns=2,
    )

    first = ConversationTurn(
        business_id="business-1",
        role=ConversationRole.USER,
        content="First",
    )
    second = ConversationTurn(
        business_id="business-1",
        role=ConversationRole.ASSISTANT,
        content="Second",
    )
    third = ConversationTurn(
        business_id="business-1",
        role=ConversationRole.USER,
        content="Third",
    )

    history = history.append(first)
    history = history.append(second)
    history = history.append(third)

    assert history.turns == (second, third)
    assert len(history.turns) == 2


def test_default_history_retains_all_turns_in_long_conversation():
    history = ConversationHistory(
        business_id="business-1",
    )

    for number in range(1, 257):
        history = history.append(
            ConversationTurn(
                business_id="business-1",
                role=ConversationRole.USER,
                content=f"Turn {number}",
            )
        )

    assert history.max_turns is None
    assert len(history.turns) == 256

    assert [turn.content for turn in history.turns] == [
        f"Turn {number}"
        for number in range(1, 257)
    ]

    assert all(
        turn.business_id == "business-1"
        for turn in history.turns
    )


def test_cross_business_turn_is_rejected():
    history = ConversationHistory(business_id="business-1")

    foreign_turn = ConversationTurn(
        business_id="business-2",
        role=ConversationRole.USER,
        content="This belongs elsewhere.",
    )

    with pytest.raises(ValueError, match="does not belong to this business"):
        history.append(foreign_turn)


def test_cross_business_turn_cannot_construct_history():
    foreign_turn = ConversationTurn(
        business_id="business-2",
        role=ConversationRole.USER,
        content="Foreign conversation.",
    )

    with pytest.raises(ValueError, match="does not belong to this business"):
        ConversationHistory(
            business_id="business-1",
            turns=(foreign_turn,),
        )


def test_invalid_turn_role_is_rejected():
    with pytest.raises(TypeError, match="ConversationRole"):
        ConversationTurn(
            business_id="business-1",
            role="user",
            content="Hello",
        )


def test_empty_turn_content_is_rejected():
    with pytest.raises(ValueError, match="content"):
        ConversationTurn(
            business_id="business-1",
            role=ConversationRole.USER,
            content="   ",
        )


def test_invalid_max_turns_is_rejected():
    with pytest.raises(ValueError, match="positive integer"):
        ConversationHistory(
            business_id="business-1",
            max_turns=0,
        )


def test_history_cannot_exceed_max_turns_at_construction():
    first = ConversationTurn(
        business_id="business-1",
        role=ConversationRole.USER,
        content="First",
    )
    second = ConversationTurn(
        business_id="business-1",
        role=ConversationRole.ASSISTANT,
        content="Second",
    )

    with pytest.raises(ValueError, match="max_turns"):
        ConversationHistory(
            business_id="business-1",
            turns=(first, second),
            max_turns=1,
        )


def test_turn_and_history_are_immutable():
    turn = ConversationTurn(
        business_id="business-1",
        role=ConversationRole.USER,
        content="Immutable",
    )

    with pytest.raises(AttributeError):
        turn.content = "Changed"

    history = ConversationHistory(
        business_id="business-1",
        turns=(turn,),
    )

    with pytest.raises(AttributeError):
        history.turns = ()
