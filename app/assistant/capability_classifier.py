from app.assistant.capability import (
    Capability,
    CapabilityDecision,
)


class CapabilityClassifier:
    """Classifies an interpreted assistant request by capability."""

    def classify(
        self,
        intent: str,
    ) -> CapabilityDecision:
        if not isinstance(intent, str):
            raise TypeError(
                "intent must be a string."
            )

        normalized = intent.strip().lower()

        if not normalized:
            raise ValueError(
                "intent must be a non-empty string."
            )

        if normalized in {
            "research",
            "web_research",
            "market_research",
            "competitor_research",
            "industry_research",
            "news_research",
        }:
            return CapabilityDecision(
                capability=Capability.RESEARCH,
                requires_authorization=True,
                reason="The request requires fresh external research.",
            )

        if normalized in {
            "send_message",
            "communication",
            "whatsapp",
            "facebook_message",
            "email",
        }:
            return CapabilityDecision(
                capability=Capability.COMMUNICATION,
                requires_authorization=True,
                reason="The request may communicate externally.",
            )

        if normalized in {
            "automation",
            "schedule",
            "reminder",
        }:
            return CapabilityDecision(
                capability=Capability.AUTOMATION,
                requires_authorization=True,
                reason="The request changes or schedules an automated action.",
            )

        if normalized in {
            "memory",
            "remember",
            "recall",
        }:
            return CapabilityDecision(
                capability=Capability.MEMORY,
                requires_authorization=False,
                reason="The request concerns business memory.",
            )

        if normalized in {
            "voice",
            "speak",
            "speech",
        }:
            return CapabilityDecision(
                capability=Capability.VOICE,
                requires_authorization=False,
                reason="The request concerns voice interaction.",
            )

        return CapabilityDecision(
            capability=Capability.CONVERSATION,
            requires_authorization=False,
            reason="The request can be handled as ordinary conversation.",
        )
