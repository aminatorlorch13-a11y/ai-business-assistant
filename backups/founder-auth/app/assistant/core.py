from app.assistant.request import AssistantRequest
from app.assistant.response import AssistantResponse
from app.models.business import Business


class AssistantCore:
    """Handles the assistant's basic request/response boundary."""

    def __init__(self, business: Business) -> None:
        if not isinstance(business, Business):
            raise TypeError("business must be a Business.")

        self._business = business

    def handle(self, request: AssistantRequest) -> AssistantResponse:
        """Handle a validated request belonging to the active business."""

        if not isinstance(request, AssistantRequest):
            raise TypeError("request must be an AssistantRequest.")

        if request.business_id != self._business.business_id:
            raise ValueError("Request does not belong to this business.")

        return AssistantResponse(
            business_id=self._business.business_id,
            assistant_name=self._business.assistant_name,
            message=request.message,
        )
