from collections.abc import Mapping

from app.ai.raw_provider import RawAIProvider


def test_raw_ai_provider_is_abstract():
    assert issubclass(RawAIProvider, object)


def test_raw_ai_provider_requires_generate_implementation():
    try:
        RawAIProvider()
    except TypeError:
        pass
    else:
        raise AssertionError("RawAIProvider should be abstract")
