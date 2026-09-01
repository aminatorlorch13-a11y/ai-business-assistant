from app.automation.event import AutomationEvent


EVENT_TO_MODULE = {
    "email_received": "email_responder",
    "form_submitted": "intake_sorting",
    "order_received": "intake_sorting",
    "appointment_created": "reminders",
    "reminder_due": "reminders",
}


class AutomationRouter:
    """Maps automation events to supported automation modules."""

    @staticmethod
    def module_for(event: AutomationEvent) -> str:
        """Return the automation module responsible for an event."""

        if not isinstance(event, AutomationEvent):
            raise TypeError("event must be an AutomationEvent.")

        try:
            return EVENT_TO_MODULE[event.event_type]
        except KeyError as exc:
            raise ValueError(
                f"No automation module is mapped to event type: "
                f"{event.event_type}"
            ) from exc
