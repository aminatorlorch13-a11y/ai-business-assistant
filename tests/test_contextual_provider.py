from app.ai.contextual_provider import ContextualAIProvider


def test_contextual_provider_defines_contextual_interpretation_contract():
    assert hasattr(ContextualAIProvider, "interpret_with_context")
