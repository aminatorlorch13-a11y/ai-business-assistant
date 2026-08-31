from app.assistant.request import AssistantRequest
from app.assistant.response import AssistantResponse
from app.models.business import Business


class AssistantCore:
    """Core controller for the business assistant."""

    def __init__(self, business: Business) -> None:
        self._business = business

    def handle(self, request: AssistantRequest) -> AssistantResponse:
        """Handle a request belonging to this business."""

        if request.business_id != self._business.business_id:
            raise ValueError("Request does not belong to this business.")

        return AssistantResponse(
            business_id=self._business.business_id,
            assistant_name=self._business.assistant_name,
            message=request.message,
        )
