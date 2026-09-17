from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from app.delivery.state import DeliveryState
from app.identity.models import UserRole


WhatsAppMessageStatus = DeliveryState


@dataclass(frozen=True)
class WhatsAppBinding:
    binding_id: str
    provider: str
    provider_account_id: str
    sender_id_hash: str
    user_id: str
    business_id: str
    role: UserRole
    active: bool = True

    def __post_init__(self) -> None:
        values = {
            "binding_id": self.binding_id,
            "provider": self.provider,
            "provider_account_id": self.provider_account_id,
            "sender_id_hash": self.sender_id_hash,
            "user_id": self.user_id,
            "business_id": self.business_id,
        }

        for name, value in values.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string.")

        if not isinstance(self.role, UserRole):
            raise TypeError("role must be a UserRole.")

        if not isinstance(self.active, bool):
            raise TypeError("active must be a bool.")


@dataclass(frozen=True)
class WhatsAppInboundMessage:
    provider: str
    provider_account_id: str
    provider_message_id: str
    sender_id_hash: str
    received_at: datetime
    text: str

    def __post_init__(self) -> None:
        for name, value in {
            "provider": self.provider,
            "provider_account_id": self.provider_account_id,
            "provider_message_id": self.provider_message_id,
            "sender_id_hash": self.sender_id_hash,
            "text": self.text,
        }.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string.")

        if not isinstance(self.received_at, datetime):
            raise TypeError("received_at must be a datetime.")

        if self.received_at.tzinfo is None:
            raise ValueError("received_at must be timezone-aware.")
