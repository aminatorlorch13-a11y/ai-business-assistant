from app.assistant.action import AssistantAction
from app.services.business_operation import BusinessOperation


class AppointmentOperation(BusinessOperation):
    """Handles appointment-related assistant actions."""

    def execute(self, action: AssistantAction) -> str:
        """Execute an appointment action."""

        if action.target != "appointment":
            raise ValueError(
                "AppointmentOperation requires an appointment target."
            )

        if action.action_type == "create":
            return "Appointment creation requested."

        if action.action_type == "update":
            return "Appointment update requested."

        if action.action_type == "delete":
            return "Appointment deletion requested."

        if action.action_type == "none":
            return "No appointment operation required."

        raise ValueError(
            f"Unsupported appointment action: {action.action_type}"
        )
