from dataclasses import dataclass
from enum import Enum


DEFAULT_LAUNCH_TARGET = 10


class LaunchProgramStatus(str, Enum):
    """
    Lifecycle state of the initial business acquisition program.

    Launch-program state does not authorize capabilities, process payments,
    determine pricing, or execute AI actions.
    """

    OPEN = "open"
    CLOSED = "closed"


@dataclass(frozen=True)
class LaunchProgram:
    """
    Immutable state for the initial paying-business acquisition program.
    """

    target_businesses: int = DEFAULT_LAUNCH_TARGET
    paid_businesses: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.target_businesses, int):
            raise TypeError(
                "target_businesses must be an integer."
            )

        if isinstance(self.target_businesses, bool):
            raise TypeError(
                "target_businesses must be an integer."
            )

        if self.target_businesses <= 0:
            raise ValueError(
                "target_businesses must be greater than zero."
            )

        if not isinstance(self.paid_businesses, int):
            raise TypeError(
                "paid_businesses must be an integer."
            )

        if isinstance(self.paid_businesses, bool):
            raise TypeError(
                "paid_businesses must be an integer."
            )

        if self.paid_businesses < 0:
            raise ValueError(
                "paid_businesses must not be negative."
            )

        if self.paid_businesses > self.target_businesses:
            raise ValueError(
                "paid_businesses cannot exceed target_businesses."
            )

    @property
    def remaining_businesses(self) -> int:
        """
        Return how many paying businesses remain to reach the target.
        """
        return self.target_businesses - self.paid_businesses

    @property
    def status(self) -> LaunchProgramStatus:
        """
        Return the current lifecycle status of the launch program.
        """
        if self.paid_businesses >= self.target_businesses:
            return LaunchProgramStatus.CLOSED

        return LaunchProgramStatus.OPEN
