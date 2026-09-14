from __future__ import annotations

from enum import Enum


class DeliveryState(str, Enum):
    PROCESSING = "processing"
    DELIVERY_PENDING = "delivery_pending"
    DELIVERY_ATTEMPTED = "delivery_attempted"
    DELIVERED = "delivered"
    CONVERSATION_PERSISTED = "conversation_persisted"
    COMPLETED = "completed"
    FAILED = "failed"
    DELIVERY_UNKNOWN = "delivery_unknown"
