from abc import ABC, abstractmethod

from app.assistant.action import AssistantAction


class BusinessOperation(ABC):
    """Interface for operations the assistant can perform for a business."""

    @abstractmethod
    def execute(self, action: AssistantAction) -> str:
        """Execute an authorized business action."""
        raise NotImplementedError
