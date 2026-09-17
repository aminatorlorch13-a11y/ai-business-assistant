from datetime import datetime, timezone

import pytest

from app.identity.models import UserRole
from app.whatsapp.models import (
    WhatsAppBinding,
    WhatsAppInboundMessage,
    WhatsAppMessageStatus,
)


def test_binding_requires_user_and_business():
    with pytest.raises(ValueError):
        WhatsAppBinding(
            binding_id="binding",
            provider="meta",
            provider_account_id="account",
            sender_id_hash="hash",
            user_id="",
            business_id="business",
            role=UserRole.OWNER,
        )


def test_binding_rejects_invalid_role():
    with pytest.raises(TypeError):
        WhatsAppBinding(
            binding_id="binding",
            provider="meta",
            provider_account_id="account",
            sender_id_hash="hash",
            user_id="user",
            business_id="business",
            role="owner",
        )


def test_binding_rejects_non_boolean_active():
    with pytest.raises(TypeError):
        WhatsAppBinding(
            binding_id="binding",
            provider="meta",
            provider_account_id="account",
            sender_id_hash="hash",
            user_id="user",
            business_id="business",
            role=UserRole.OWNER,
            active=1,
        )


def test_inbound_message_requires_timezone_aware_timestamp():
    with pytest.raises(ValueError):
        WhatsAppInboundMessage(
            provider="meta",
            provider_account_id="account",
            provider_message_id="message",
            sender_id_hash="hash",
            received_at=datetime.now(),
            text="hello",
        )


def test_message_status_values_are_stable():
    assert WhatsAppMessageStatus.PROCESSING.value == "processing"
    assert WhatsAppMessageStatus.COMPLETED.value == "completed"
    assert WhatsAppMessageStatus.FAILED.value == "failed"
