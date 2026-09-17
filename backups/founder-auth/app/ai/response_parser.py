from collections.abc import Mapping

from app.assistant.action import AssistantAction
from app.assistant.intent import AssistantIntent
from app.assistant.interpretation import AIInterpretation


# ============================================================================
# AI RESPONSE SECURITY CONTRACT
# ============================================================================
#
# This module is a security boundary.
#
# AI output is UNTRUSTED input.
#
# The parser is responsible for:
#   1. Structural validation
#   2. Type validation
#   3. Required-field validation
#   4. Closed-world intent validation
#   5. Closed-world action validation
#   6. Tenant/business identity protection
#
# The application-supplied business_id is ALWAYS authoritative.
# An AI-supplied business_id may only confirm that identity.
#
# It must NEVER be used to select a tenant.
# ============================================================================


ALLOWED_INTENTS = frozenset(
    {
        "general_question",
        "customer_request",
        "business_task",
    }
)

ALLOWED_ACTIONS = frozenset(
    {
        "none",
        "create",
        "update",
        "delete",
    }
)


class AIResponseParser:
    """
    Convert untrusted AI output into a validated AIInterpretation.

    Security invariants:

    - Input must be a mapping.
    - Every required field must exist.
    - Required textual fields must contain strings.
    - Non-semantic textual fields must not be blank.
    - Intent values must belong to ALLOWED_INTENTS.
    - Action values must belong to ALLOWED_ACTIONS.
    - The application-supplied business_id is authoritative.
    - An AI-supplied business_id, when present, must exactly match the
      trusted application business_id.
    - The AI can never establish, override, or redirect tenant identity.
    - The resulting interpretation always receives business_id from the
      application argument, never from AI output.
    """

    REQUIRED_FIELDS = frozenset(
        {
            "intent_type",
            "instruction",
            "action_type",
            "target",
            "action_instruction",
        }
    )

    STRING_FIELDS = (
        "intent_type",
        "instruction",
        "action_type",
        "target",
        "action_instruction",
    )

    SEMANTIC_FIELDS = frozenset(
        {
            "intent_type",
            "action_type",
        }
    )

    def parse(
        self,
        data: Mapping[str, object],
        business_id: str,
    ) -> AIInterpretation:
        """
        Validate and convert an AI response.

        Args:
            data:
                Untrusted structured output produced by the AI layer.

            business_id:
                Trusted business/tenant identity supplied by the
                application layer.

        Returns:
            A validated AIInterpretation bound exclusively to the trusted
            application business_id.

        Raises:
            ValueError:
                If the trusted identity or AI response violates the
                parser security contract.
        """

        # ------------------------------------------------------------------
        # SECURITY BOUNDARY 1:
        # Validate the identity supplied by the trusted application layer.
        # ------------------------------------------------------------------
        self._validate_business_id(business_id)

        # ------------------------------------------------------------------
        # SECURITY BOUNDARY 2:
        # Validate the AI response container.
        # ------------------------------------------------------------------
        self._validate_mapping(data)

        # ------------------------------------------------------------------
        # STRUCTURAL VALIDATION:
        # Every required field must be present.
        # ------------------------------------------------------------------
        missing = self.REQUIRED_FIELDS - data.keys()

        if missing:
            raise ValueError(
                f"AI response is missing required fields: {sorted(missing)}."
            )

        # ------------------------------------------------------------------
        # TYPE / CONTENT VALIDATION:
        # ------------------------------------------------------------------
        self._validate_string_fields(data)

        intent_type = data["intent_type"]
        instruction = data["instruction"]
        action_type = data["action_type"]
        target = data["target"]
        action_instruction = data["action_instruction"]

        # ------------------------------------------------------------------
        # TENANT SECURITY:
        #
        # business_id inside AI output is NEVER authoritative.
        #
        # If present, it is merely an assertion that must agree with the
        # trusted application identity.
        # ------------------------------------------------------------------
        if "business_id" in data:
            supplied_business_id = data["business_id"]

            self._validate_supplied_business_id(
                supplied_business_id,
                business_id,
            )

        # ------------------------------------------------------------------
        # CLOSED-WORLD SEMANTIC VALIDATION:
        # ------------------------------------------------------------------
        if intent_type not in ALLOWED_INTENTS:
            raise ValueError(
                f"Unknown intent for field intent_type: {intent_type}."
            )

        if action_type not in ALLOWED_ACTIONS:
            raise ValueError(
                f"Unknown action for field action_type: {action_type}."
            )

        # ------------------------------------------------------------------
        # TRUSTED OBJECT CONSTRUCTION:
        #
        # CRITICAL:
        #
        # The business_id used here MUST come from the application.
        #
        # Never replace this with:
        #
        #     data.get("business_id")
        #
        # ------------------------------------------------------------------
        return AIInterpretation(
            intent=AssistantIntent(
                business_id=business_id,
                intent_type=intent_type,
                instruction=instruction,
            ),
            action=AssistantAction(
                business_id=business_id,
                action_type=action_type,
                target=target,
                instruction=action_instruction,
            ),
        )

    @staticmethod
    def _validate_business_id(business_id: object) -> None:
        """
        Validate the trusted application business identity.

        This identity is supplied by the application and is the only
        authoritative tenant identity accepted by the parser.
        """

        if not isinstance(business_id, str):
            raise ValueError("business_id must be a string.")

        if not business_id.strip():
            raise ValueError(
                "business_id must be a non-empty string."
            )

    @staticmethod
    def _validate_supplied_business_id(
        supplied_business_id: object,
        trusted_business_id: str,
    ) -> None:
        """
        Validate an optional business_id supplied by the AI.

        The AI value is never trusted as tenant authority.

        Accepted:
            AI business_id == trusted application business_id

        Rejected:
            Wrong type
            Empty string
            Whitespace-only string
            Different business_id
        """

        if not isinstance(supplied_business_id, str):
            raise ValueError(
                "AI response business_id must be a string."
            )

        if not supplied_business_id.strip():
            raise ValueError(
                "AI response business_id must be a non-empty string."
            )

        if supplied_business_id != trusted_business_id:
            raise ValueError(
                "AI response business_id does not belong to this business."
            )

    @staticmethod
    def _validate_mapping(data: object) -> None:
        """Validate that AI output is a mapping."""

        if not isinstance(data, Mapping):
            raise ValueError(
                "AI response must be a mapping."
            )

    @classmethod
    def _validate_string_fields(
        cls,
        data: Mapping[str, object],
    ) -> None:
        """
        Validate required textual fields.

        intent_type and action_type intentionally skip blank-string
        validation because they are semantic enum fields.

        This allows invalid values such as "" to reach the closed-world
        validator and produce:

            Unknown intent for field intent_type: ...

        or:

            Unknown action for field action_type: ...
        """

        for field_name in cls.STRING_FIELDS:
            value = data[field_name]

            if not isinstance(value, str):
                raise ValueError(
                    f"AI response field '{field_name}' must be a string."
                )

            if (
                field_name not in cls.SEMANTIC_FIELDS
                and not value.strip()
            ):
                raise ValueError(
                    f"AI response field '{field_name}' "
                    "must be a non-empty string."
                )
