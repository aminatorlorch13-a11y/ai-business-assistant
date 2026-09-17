import pytest

from app.automation.configuration import AutomationConfiguration


def make_configuration() -> AutomationConfiguration:
    return AutomationConfiguration(
        business_id="business-001",
        email_responder_enabled=True,
        intake_sorting_enabled=True,
        reminders_enabled=False,
    )


def test_configuration_accepts_valid_input():
    configuration = make_configuration()

    assert configuration.business_id == "business-001"
    assert configuration.email_responder_enabled is True
    assert configuration.intake_sorting_enabled is True
    assert configuration.reminders_enabled is False


@pytest.mark.parametrize(
    "business_id",
    ["", "   ", None, 123],
)
def test_configuration_rejects_invalid_business_id(business_id):
    with pytest.raises((TypeError, ValueError), match="business_id"):
        AutomationConfiguration(
            business_id=business_id,
        )


@pytest.mark.parametrize(
    "field_name",
    [
        "email_responder_enabled",
        "intake_sorting_enabled",
        "reminders_enabled",
    ],
)
def test_configuration_rejects_non_boolean_module_settings(field_name):
    values = {
        "email_responder_enabled": False,
        "intake_sorting_enabled": False,
        "reminders_enabled": False,
    }

    values[field_name] = "true"

    with pytest.raises(TypeError, match=field_name):
        AutomationConfiguration(
            business_id="business-001",
            **values,
        )


def test_configuration_reports_enabled_module():
    configuration = make_configuration()

    assert configuration.module_enabled("email_responder") is True
    assert configuration.module_enabled("intake_sorting") is True
    assert configuration.module_enabled("reminders") is False


def test_configuration_rejects_unknown_module():
    configuration = make_configuration()

    with pytest.raises(ValueError, match="Unknown automation module"):
        configuration.module_enabled("unknown")


def test_configuration_is_immutable():
    configuration = make_configuration()

    with pytest.raises(AttributeError):
        configuration.reminders_enabled = True
