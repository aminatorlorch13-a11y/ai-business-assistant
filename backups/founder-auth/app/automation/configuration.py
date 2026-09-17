from dataclasses import dataclass


@dataclass(frozen=True)
class AutomationConfiguration:
    """Business-specific configuration for the automation engine."""

    business_id: str
    email_responder_enabled: bool = False
    intake_sorting_enabled: bool = False
    reminders_enabled: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.business_id, str):
            raise TypeError("business_id must be a string.")

        if not self.business_id.strip():
            raise ValueError("business_id must be a non-empty string.")

        for field_name in (
            "email_responder_enabled",
            "intake_sorting_enabled",
            "reminders_enabled",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise TypeError(f"{field_name} must be a boolean.")

    def module_enabled(self, module: str) -> bool:
        """Return whether a supported automation module is enabled."""

        modules = {
            "email_responder": self.email_responder_enabled,
            "intake_sorting": self.intake_sorting_enabled,
            "reminders": self.reminders_enabled,
        }

        if module not in modules:
            raise ValueError(f"Unknown automation module: {module}")

        return modules[module]
