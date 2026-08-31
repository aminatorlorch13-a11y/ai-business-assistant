from app.assistant.action import AssistantAction
from app.trust.action_policy import ActionPolicy


def make_action(action_type: str) -> AssistantAction:
    return AssistantAction(
        business_id="business-001",
        action_type=action_type,
        target="appointment",
        instruction="Perform the requested operation.",
    )


def test_policy_allows_none_action():
    policy = ActionPolicy()

    assert policy.allows(make_action("none")) is True


def test_policy_allows_create_by_default():
    policy = ActionPolicy()

    assert policy.allows(make_action("create")) is True


def test_policy_allows_update_by_default():
    policy = ActionPolicy()

    assert policy.allows(make_action("update")) is True


def test_policy_denies_delete_by_default():
    policy = ActionPolicy()

    assert policy.allows(make_action("delete")) is False


def test_policy_can_disable_create():
    policy = ActionPolicy(allow_create=False)

    assert policy.allows(make_action("create")) is False


def test_policy_can_disable_update():
    policy = ActionPolicy(allow_update=False)

    assert policy.allows(make_action("update")) is False


def test_policy_can_enable_delete():
    policy = ActionPolicy(allow_delete=True)

    assert policy.allows(make_action("delete")) is True
