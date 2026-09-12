from abc import ABC, abstractmethod

from app.assistant.action import AssistantAction
from app.identity.tenant import TenantContext


class BusinessOperation(ABC):
    """Interface for operations the assistant can perform for a business."""

    @abstractmethod
    def execute(
        self,
        action: AssistantAction,
        tenant: TenantContext | None = None,
    ) -> str:
        """Execute an authorized business action."""
        raise NotImplementedError
