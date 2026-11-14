from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import re

TIME_FIELDS = {
    "wake_time", "sleep_time", "work_start", "work_end",
    "quiet_start", "quiet_end", "briefing_time",
}
ROUTINE_FIELDS = TIME_FIELDS - {"briefing_time"}
CHANNELS = {"whatsapp", "sms", "email", "voice", "companion_app"}


def validate_time(value, name):
    if value is not None and (
        not isinstance(value, str)
        or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value)
    ):
        raise ValueError(f"{name} must use HH:MM format.")


@dataclass(frozen=True, slots=True)
class OwnerLifestylePreferences:
    business_id: str
    user_id: str
    timezone: str = "UTC"
    wake_time: str | None = None
    sleep_time: str | None = None
    work_start: str | None = None
    work_end: str | None = None
    quiet_start: str | None = None
    quiet_end: str | None = None
    briefing_enabled: bool = True
    briefing_time: str = "07:00"
    initiative_level: str = "balanced"
    personality: str = "natural"
    preferred_channels: tuple[str, ...] = field(default_factory=lambda: ("whatsapp",))
    critical_alerts_during_quiet: bool = True
    created_at: str | None = None
    updated_at: str | None = None

    def __post_init__(self):
        for name in ("business_id", "user_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip() or len(value) > 128:
                raise ValueError(f"Invalid {name}.")
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, TypeError, ValueError) as exc:
            raise ValueError("Invalid IANA timezone.") from exc
        for name in TIME_FIELDS:
            validate_time(getattr(self, name), name)
        if self.initiative_level not in {"balanced", "high", "owner_led"}:
            raise ValueError("Invalid initiative level.")
        if self.personality != "natural":
            raise ValueError("Unsupported personality.")
        if not isinstance(self.preferred_channels, tuple) or not self.preferred_channels:
            raise ValueError("Channels must be a non-empty tuple.")
        if any(c not in CHANNELS for c in self.preferred_channels):
            raise ValueError("Unsupported communication channel.")
        if len(set(self.preferred_channels)) != len(self.preferred_channels):
            raise ValueError("Duplicate communication channels.")
        for name in ("briefing_enabled", "critical_alerts_during_quiet"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be boolean.")


@dataclass(frozen=True, slots=True)
class RoutineSuggestion:
    suggestion_id: str
    business_id: str
    user_id: str
    field_name: str
    proposed_value: str
    observation_count: int
    first_observed_at: str
    last_observed_at: str
    status: str = "pending"

    resolved_at: str | None = None
    def __post_init__(self):
        if self.field_name not in ROUTINE_FIELDS:
            raise ValueError("Unsupported routine field.")
        validate_time(self.proposed_value, self.field_name)
        if self.status not in {"pending", "accepted", "rejected"}:
            raise ValueError("Invalid suggestion status.")
        if self.observation_count < 1:
            raise ValueError("Invalid observation count.")
