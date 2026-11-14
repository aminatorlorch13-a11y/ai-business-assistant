import json
from io import BytesIO
from urllib.error import HTTPError

import pytest

from app.voice.elevenlabs_engine import (
    ElevenLabsConfig,
    ElevenLabsSpeechEngine,
)
from app.voice.request import SpeechRequest


class FakeResponse:
    def __init__(self, audio):
        self.audio = audio

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size=-1):
        return self.audio[:size]


def make_engine():
    config = ElevenLabsConfig(
        api_key="test-secret",
        male_voice_id="male-test-id",
        female_voice_id="female-test-id",
    )
    return ElevenLabsSpeechEngine(config)


def test_synthesize_returns_real_audio_bytes(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = request.headers
        captured["payload"] = json.loads(request.data)
        captured["timeout"] = timeout
        return FakeResponse(b"ID3-test-mp3-audio")

    monkeypatch.setattr(
        "app.voice.elevenlabs_engine.urlopen",
        fake_urlopen,
    )

    audio = make_engine().synthesize(
        SpeechRequest(text="Hello Amination", voice="male", speed=1.0)
    )

    assert audio == b"ID3-test-mp3-audio"
    assert "/male-test-id/stream?" in captured["url"]
    assert "mp3_44100_128" in captured["url"]
    assert captured["headers"]["Xi-api-key"] == "test-secret"
    assert captured["payload"] == {
        "text": "Hello Amination",
        "model_id": "eleven_v4_turbo",
    }
    assert captured["timeout"] == 30.0


def test_synthesize_uses_selected_female_voice(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        return FakeResponse(b"female-audio")

    monkeypatch.setattr(
        "app.voice.elevenlabs_engine.urlopen",
        fake_urlopen,
    )

    audio = make_engine().synthesize(
        SpeechRequest(text="Hello", voice="female", speed=1.0)
    )

    assert audio == b"female-audio"
    assert "/female-test-id/stream?" in captured["url"]


def test_provider_http_error_is_sanitized(monkeypatch):
    def fake_urlopen(request, timeout):
        raise HTTPError(
            request.full_url,
            401,
            "Unauthorized",
            {},
            BytesIO(b"private provider response"),
        )

    monkeypatch.setattr(
        "app.voice.elevenlabs_engine.urlopen",
        fake_urlopen,
    )

    with pytest.raises(RuntimeError, match="HTTP 401") as error:
        make_engine().synthesize(
            SpeechRequest(text="Hello", voice="male")
        )

    assert "private provider response" not in str(error.value)
    assert "test-secret" not in str(error.value)


def test_empty_audio_is_rejected(monkeypatch):
    monkeypatch.setattr(
        "app.voice.elevenlabs_engine.urlopen",
        lambda request, timeout: FakeResponse(b""),
    )

    with pytest.raises(RuntimeError, match="empty audio"):
        make_engine().synthesize(
            SpeechRequest(text="Hello", voice="male")
        )


def test_oversized_audio_is_rejected(monkeypatch):
    monkeypatch.setattr(
        "app.voice.elevenlabs_engine.urlopen",
        lambda request, timeout: FakeResponse(
            b"x" * (ElevenLabsSpeechEngine.MAX_AUDIO_BYTES + 1)
        ),
    )

    with pytest.raises(RuntimeError, match="size limit"):
        make_engine().synthesize(
            SpeechRequest(text="Hello", voice="male")
        )


def test_environment_configuration_requires_all_credentials(monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.delenv("ELEVENLABS_VOICE_ID_MALE", raising=False)
    monkeypatch.delenv("ELEVENLABS_VOICE_ID_FEMALE", raising=False)

    with pytest.raises(RuntimeError, match="not configured"):
        ElevenLabsConfig.from_environment()


def test_environment_configuration_loads_without_exposing_secrets(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "private-test-key")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID_MALE", "male-id")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID_FEMALE", "female-id")
    monkeypatch.setenv("ELEVENLABS_TIMEOUT_SECONDS", "45")

    config = ElevenLabsConfig.from_environment()

    assert config.api_key == "private-test-key"
    assert config.male_voice_id == "male-id"
    assert config.female_voice_id == "female-id"
    assert config.timeout_seconds == 45.0
    assert config.model_id == "eleven_flash_v2_5"


def test_expressive_vocalizations_are_rendered_as_eleven_v4_audio_tags():
    from app.voice.request import SpeechRequest, VocalizationEvent

    config = ElevenLabsConfig(
        api_key="test-key",
        male_voice_id="male-id",
        female_voice_id="female-id",
        model_id="eleven_v4",
    )
    engine = ElevenLabsSpeechEngine(config)

    request = SpeechRequest(
        text="That was unexpected. I am glad you are here.",
        voice="female",
        emotion="excited",
        delivery="whisper",
        vocalizations=(
            VocalizationEvent("chuckle", 0),
            VocalizationEvent("sigh", 21),
        ),
    )

    rendered = engine._prepare_expressive_text(request)

    assert rendered.startswith("[excited] [whispers]")
    assert "[chuckles]" in rendered
    assert "[sighs]" in rendered
    assert "That was unexpected." in rendered
    assert "I am glad you are here." in rendered


def test_flash_model_rejects_vocalization_tags_instead_of_speaking_them():
    from app.voice.request import SpeechRequest, VocalizationEvent

    config = ElevenLabsConfig(
        api_key="test-key",
        male_voice_id="male-id",
        female_voice_id="female-id",
        model_id="eleven_flash_v2_5",
    )
    engine = ElevenLabsSpeechEngine(config)

    request = SpeechRequest(
        text="Hello.",
        voice="female",
        vocalizations=(VocalizationEvent("laugh", 0),),
    )

    with pytest.raises(ValueError, match="does not support expressive audio tags"):
        engine._prepare_expressive_text(request)


def test_neutral_flash_request_keeps_original_text():
    from app.voice.request import SpeechRequest

    config = ElevenLabsConfig(
        api_key="test-key",
        male_voice_id="male-id",
        female_voice_id="female-id",
        model_id="eleven_flash_v2_5",
    )
    engine = ElevenLabsSpeechEngine(config)

    request = SpeechRequest(
        text="Hello, how are you?",
        voice="female",
    )

    assert engine._prepare_expressive_text(request) == "Hello, how are you?"
