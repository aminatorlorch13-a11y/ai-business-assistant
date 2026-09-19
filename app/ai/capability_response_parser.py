from __future__ import annotations

from collections.abc import Mapping

from app.assistant.ai_capability_request import AICapabilityRequest
from app.assistant.ai_result import AIResult
from app.assistant.capability import Capability


class AICapabilityResponseParser:
    """
    Security boundary for the new structured AI result contract.

    AI output is untrusted input.

    The parser converts raw provider output into AIResult only after:
    - container validation
    - closed-world field validation
    - response validation
    - capability validation
    - capability-request structure validation
    - argument-container validation
    - primitive proposal validation

    This parser does not authorize or execute anything.
    """

    REQUIRED_FIELDS = frozenset(
        {
            "response",
            "capability_requests",
        }
    )

    ALLOWED_FIELDS = REQUIRED_FIELDS

    REQUEST_REQUIRED_FIELDS = frozenset(
        {
            "capability",
            "operation",
            "arguments",
            "reason",
            "reversible",
        }
    )

    REQUEST_ALLOWED_FIELDS = REQUEST_REQUIRED_FIELDS

    def parse(self, data: Mapping[str, object]) -> AIResult:
        """
        Validate untrusted structured AI output and return an AIResult.

        The parser deliberately does not accept business identity because
        tenant identity belongs to the trusted application layer.
        """
        self._validate_mapping(data)

        missing = self.REQUIRED_FIELDS - data.keys()
        if missing:
            raise ValueError(
                f"AI result is missing required fields: {sorted(missing)}."
            )

        unknown = data.keys() - self.ALLOWED_FIELDS
        if unknown:
            raise ValueError(
                f"AI result contains unknown fields: {sorted(unknown)}."
            )

        response = self._parse_response(data["response"])
        capability_requests = self._parse_capability_requests(
            data["capability_requests"]
        )

        return AIResult(
            response=response,
            capability_requests=capability_requests,
        )

    @staticmethod
    def _validate_mapping(data: object) -> None:
        if not isinstance(data, Mapping):
            raise ValueError("AI result must be a mapping.")

    @staticmethod
    def _parse_response(value: object) -> str | None:
        if value is None:
            return None

        if not isinstance(value, str):
            raise ValueError("AI result field 'response' must be a string or null.")

        value = value.strip()

        if not value:
            return None

        return value

    @classmethod
    def _parse_capability_requests(
        cls,
        value: object,
    ) -> tuple[AICapabilityRequest, ...]:
        if not isinstance(value, list):
            raise ValueError(
                "AI result field 'capability_requests' must be a list."
            )

        requests: list[AICapabilityRequest] = []

        for index, raw_request in enumerate(value):
            try:
                requests.append(cls._parse_capability_request(raw_request))
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"Invalid capability request at index {index}: {exc}"
                ) from exc

        return tuple(requests)

    @classmethod
    def _parse_capability_request(
        cls,
        data: object,
    ) -> AICapabilityRequest:
        if not isinstance(data, Mapping):
            raise ValueError("capability request must be a mapping.")

        missing = cls.REQUEST_REQUIRED_FIELDS - data.keys()
        if missing:
            raise ValueError(
                "capability request is missing required fields: "
                f"{sorted(missing)}."
            )

        unknown = data.keys() - cls.REQUEST_ALLOWED_FIELDS
        if unknown:
            raise ValueError(
                "capability request contains unknown fields: "
                f"{sorted(unknown)}."
            )

        capability_value = data["capability"]

        if not isinstance(capability_value, str):
            raise ValueError("capability must be a string.")

        try:
            capability = Capability(capability_value)
        except ValueError as exc:
            raise ValueError(
                f"Unknown capability: {capability_value}."
            ) from exc

        operation = data["operation"]
        if not isinstance(operation, str):
            raise ValueError("operation must be a string.")
        if not operation.strip():
            raise ValueError("operation must be a non-empty string.")

        arguments = data["arguments"]
        if not isinstance(arguments, Mapping):
            raise ValueError("arguments must be a mapping.")

        reason = data["reason"]
        if not isinstance(reason, str):
            raise ValueError("reason must be a string.")
        if not reason.strip():
            raise ValueError("reason must be a non-empty string.")

        reversible = data["reversible"]
        if not isinstance(reversible, bool):
            raise ValueError("reversible must be a boolean.")

        return AICapabilityRequest(
            capability=capability,
            operation=operation,
            arguments=arguments,
            reason=reason,
            reversible=reversible,
        )
