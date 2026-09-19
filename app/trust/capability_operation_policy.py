from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from app.assistant.capability import Capability


@dataclass(frozen=True)
class CapabilityOperationPolicy:
    """
    Trusted application-owned policy for registered capability operations.

    Each registered operation explicitly declares whether confirmation is
    required before execution.

    Unknown capability/operation pairs are rejected. AI proposals never
    define or influence these semantics.
    """

    confirmation_by_operation: Mapping[
        Capability,
        Mapping[str, bool],
    ]

    def __post_init__(self) -> None:
        if not isinstance(self.confirmation_by_operation, Mapping):
            raise TypeError(
                "confirmation_by_operation must be a mapping."
            )

        normalized: dict[
            Capability,
            dict[str, bool],
        ] = {}

        for capability, operations in self.confirmation_by_operation.items():
            if not isinstance(capability, Capability):
                raise TypeError(
                    "Policy capability keys must be Capability values."
                )

            if not isinstance(operations, Mapping):
                raise TypeError(
                    "Policy operations must be mappings."
                )

            normalized_operations: dict[str, bool] = {}

            for operation, requires_confirmation in operations.items():
                if not isinstance(operation, str):
                    raise TypeError(
                        "Policy operation names must be strings."
                    )

                operation = operation.strip()

                if not operation:
                    raise ValueError(
                        "Policy operation names must be non-empty."
                    )

                if not isinstance(requires_confirmation, bool):
                    raise TypeError(
                        "Confirmation requirements must be bool values."
                    )

                normalized_operations[operation] = requires_confirmation

            normalized[capability] = normalized_operations

        object.__setattr__(
            self,
            "confirmation_by_operation",
            {
                capability: dict(operations)
                for capability, operations in normalized.items()
            },
        )

    def requires_confirmation(
        self,
        capability: Capability,
        operation: str,
    ) -> bool:
        """
        Return the trusted confirmation requirement for one registered
        capability operation.

        Unknown capability/operation pairs are rejected.
        """
        if not isinstance(capability, Capability):
            raise TypeError("capability must be a Capability.")

        if not isinstance(operation, str):
            raise TypeError("operation must be a string.")

        operation = operation.strip()

        if not operation:
            raise ValueError(
                "operation must be a non-empty string."
            )

        operations = self.confirmation_by_operation.get(capability)

        if operations is None:
            raise LookupError(
                f"No policy registered for capability "
                f"'{capability.value}'."
            )

        if operation not in operations:
            raise LookupError(
                f"No policy registered for operation "
                f"'{operation}' under capability "
                f"'{capability.value}'."
            )

        return operations[operation]
