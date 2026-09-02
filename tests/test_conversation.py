from app.voice.conversation import ConversationState


def test_conversation_states_are_distinct():
    states = list(ConversationState)

    assert len(states) == 8
    assert len(set(states)) == 8


def test_conversation_states_have_stable_values():
    assert ConversationState.IDLE.value == "idle"
    assert ConversationState.LISTENING.value == "listening"
    assert ConversationState.PROCESSING.value == "processing"
    assert ConversationState.SPEAKING.value == "speaking"
    assert ConversationState.WAITING_FOR_INPUT.value == "waiting_for_input"
    assert ConversationState.STOPPING.value == "stopping"
    assert ConversationState.ENDED.value == "ended"
    assert ConversationState.ERROR.value == "error"
