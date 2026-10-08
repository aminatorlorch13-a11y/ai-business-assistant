from app.ai.privacy_context import PrivacyContext


def render_ai_context(context: PrivacyContext) -> str:
    if not isinstance(context, PrivacyContext):
        raise TypeError("context must be a PrivacyContext.")

    sections = [
        f"Application business_id: {context.business_id}",
        context.conversation_text,
        "Persistent business memory:\n" + (context.memory_text or "(none)"),
        "Automation context:\n" + context.automation_text,
    ]

    return "\n\n".join(sections)
