import pytest

from app.models.business import Business


def test_business_accepts_valid_identity():
    business = Business(
        business_id="demo-business",
        name="Demo Business",
        owner_name="Mike",
        assistant_name="Nova",
        assistant_voice="female",
    )

    assert business.business_id == "demo-business"
    assert business.name == "Demo Business"
    assert business.owner_name == "Mike"
    assert business.assistant_name == "Nova"
    assert business.assistant_voice == "female"


def test_business_rejects_invalid_voice():
    with pytest.raises(ValueError):
        Business(
            business_id="demo-business",
            name="Demo Business",
            owner_name="Mike",
            assistant_name="Nova",
            assistant_voice="robot",
        )


def test_business_rejects_empty_assistant_name():
    with pytest.raises(ValueError):
        Business(
            business_id="demo-business",
            name="Demo Business",
            owner_name="Mike",
            assistant_name="",
            assistant_voice="female",
        )


def test_business_rejects_empty_business_id():
    with pytest.raises(ValueError):
        Business(
            business_id="",
            name="Demo Business",
            owner_name="Mike",
            assistant_name="Nova",
            assistant_voice="female",
        )
