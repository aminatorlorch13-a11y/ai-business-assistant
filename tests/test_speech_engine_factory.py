from unittest.mock import patch

import pytest

from app.voice.engine_factory import build_speech_engine
from app.voice.local_engine import AndroidSpeechEngine


def test_default_provider_is_android(monkeypatch):
    monkeypatch.delenv("AMINATION_TTS_PROVIDER", raising=False)

    engine = build_speech_engine()

    assert isinstance(engine, AndroidSpeechEngine)


def test_android_provider_can_be_selected_explicitly():
    engine = build_speech_engine("android")

    assert isinstance(engine, AndroidSpeechEngine)


def test_azure_provider_uses_environment_configuration(monkeypatch):
    monkeypatch.setenv("AZURE_SPEECH_KEY", "local-test-key")
    monkeypatch.setenv("AZURE_SPEECH_REGION", "southafricanorth")

    with patch(
        "app.voice.azure_engine.AzureSpeechEngine"
    ) as azure_engine:
        result = build_speech_engine("azure")

    azure_engine.assert_called_once()
    config = azure_engine.call_args.args[0]

    assert config.subscription_key == "local-test-key"
    assert config.region == "southafricanorth"
    assert result == azure_engine.return_value


def test_azure_provider_rejects_missing_credentials(monkeypatch):
    monkeypatch.delenv("AZURE_SPEECH_KEY", raising=False)
    monkeypatch.delenv("AZURE_SPEECH_REGION", raising=False)

    with pytest.raises(ValueError, match="subscription key"):
        build_speech_engine("azure")


def test_unknown_provider_is_rejected():
    with pytest.raises(ValueError, match="Unsupported speech provider"):
        build_speech_engine("unknown")


def test_provider_must_be_a_string():
    with pytest.raises(TypeError, match="must be a string"):
        build_speech_engine(None if False else 123)
