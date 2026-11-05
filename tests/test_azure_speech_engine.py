from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.voice.azure_engine import (
    AZURE_VOICE_PROFILES,
    AzureSpeechConfig,
    AzureSpeechEngine,
)
from app.voice.request import SpeechRequest


def make_engine():
    return AzureSpeechEngine(
        AzureSpeechConfig(
            subscription_key="test-secret",
            region="southafricanorth",
        )
    )


def test_azure_config_rejects_missing_credentials():
    with pytest.raises(ValueError):
        AzureSpeechConfig("", "southafricanorth")

    with pytest.raises(ValueError):
        AzureSpeechConfig("test-secret", "")


def test_azure_config_loads_environment(monkeypatch):
    monkeypatch.setenv("AZURE_SPEECH_KEY", "local-test-key")
    monkeypatch.setenv("AZURE_SPEECH_REGION", "southafricanorth")
    monkeypatch.setenv("AZURE_SPEECH_TIMEOUT_SECONDS", "45")

    config = AzureSpeechConfig.from_environment()

    assert config.subscription_key == "local-test-key"
    assert config.region == "southafricanorth"
    assert config.timeout_seconds == 45


def test_default_azure_profiles_use_south_african_english():
    assert AZURE_VOICE_PROFILES["female"].provider_voice_id == "en-ZA-LeahNeural"
    assert AZURE_VOICE_PROFILES["male"].provider_voice_id == "en-ZA-LukeNeural"
    assert AZURE_VOICE_PROFILES["female"].language == "en-ZA"
    assert AZURE_VOICE_PROFILES["male"].language == "en-ZA"


def test_ssml_escapes_user_text():
    engine = make_engine()
    request = SpeechRequest(
        text='Amin & Amination <AI> "works".',
        voice="female",
    )

    ssml = engine._build_ssml(request)

    assert "Amin &amp; Amination &lt;AI&gt;" in ssml
    assert 'voice name="en-ZA-LeahNeural"' in ssml
    assert 'xml:lang="en-ZA"' in ssml


def test_ssml_applies_requested_speech_speed():
    engine = make_engine()
    request = SpeechRequest(
        text="Speak slowly.",
        voice="male",
        speed=0.8,
    )

    assert 'rate="80%"' in engine._build_ssml(request)


def test_ssml_rejects_speed_outside_supported_range():
    engine = make_engine()

    with pytest.raises(ValueError, match="speed"):
        engine._build_ssml(
            SpeechRequest(
                text="Too fast.",
                voice="female",
                speed=3.0,
            )
        )


def test_synthesis_sends_authenticated_ssml_request():
    engine = make_engine()
    response = MagicMock()
    response.read.return_value = b"fake-mp3-audio"
    response.__enter__.return_value = response

    with patch("urllib.request.urlopen", return_value=response) as urlopen:
        audio = engine._synthesize("<speak>hello</speak>")

    assert audio == b"fake-mp3-audio"

    request = urlopen.call_args.args[0]
    assert request.full_url == (
        "https://southafricanorth.tts.speech.microsoft.com"
        "/cognitiveservices/v1"
    )
    assert request.get_method() == "POST"
    assert request.get_header("Content-type") == "application/ssml+xml"
    assert request.get_header("X-microsoft-outputformat") == (
        "audio-24khz-48kbitrate-mono-mp3"
    )
    assert request.get_header("Ocp-apim-subscription-key") == "test-secret"
    assert request.data == b"<speak>hello</speak>"


def test_synthesis_rejects_empty_audio():
    engine = make_engine()
    response = MagicMock()
    response.read.return_value = b""
    response.__enter__.return_value = response

    with patch("urllib.request.urlopen", return_value=response):
        with pytest.raises(RuntimeError, match="empty audio"):
            engine._synthesize("<speak>hello</speak>")


def test_http_error_does_not_expose_response_body_or_secret():
    engine = make_engine()

    error = __import__("urllib.error", fromlist=["HTTPError"]).HTTPError(
        "https://example.invalid",
        401,
        "Unauthorized",
        {},
        None,
    )

    with patch("urllib.request.urlopen", side_effect=error):
        with pytest.raises(RuntimeError, match="HTTP 401") as caught:
            engine._synthesize("<speak>hello</speak>")

    assert "test-secret" not in str(caught.value)


def test_speak_plays_audio_and_removes_temporary_file():
    engine = make_engine()
    player_calls = []

    def fake_player(*args):
        player_calls.append(args)
        if args[0] == "info":
            return "Playing" if len(
                [call for call in player_calls if call[0] == "info"]
            ) == 1 else "No track currently!"
        return ""

    with (
        patch.object(engine, "_synthesize", return_value=b"fake-mp3"),
        patch.object(engine, "_player", side_effect=fake_player),
        patch(
            "app.voice.azure_engine.time",
            SimpleNamespace(
                monotonic=lambda: 100.0,
                sleep=lambda _seconds: None,
            ),
        ),
    ):
        engine.speak(SpeechRequest("Hello.", "female"))

    play_calls = [call for call in player_calls if call[0] == "play"]
    assert len(play_calls) == 1

    audio_path = play_calls[0][1]
    import os
    assert not os.path.exists(audio_path)
    assert engine._active_file is None
    assert engine._speaking is False


def test_speak_rejects_overlapping_requests():
    engine = make_engine()

    with patch.object(engine, "_synthesize", return_value=b"audio"):
        with engine._lock:
            engine._speaking = True

        with pytest.raises(RuntimeError, match="already active"):
            engine.speak(SpeechRequest("Hello.", "female"))

        with engine._lock:
            engine._speaking = False


def test_cancel_during_synthesis_prevents_playback():
    engine = make_engine()
    player = MagicMock()

    def synthesize(_ssml):
        engine.cancel_current()
        return b"audio"

    with (
        patch.object(engine, "_synthesize", side_effect=synthesize),
        patch.object(engine, "_player", player),
    ):
        engine.speak(SpeechRequest("Hello.", "female"))

    player.assert_not_called()
    assert engine._speaking is False
    assert engine._active_file is None


def test_cancel_stops_active_playback():
    engine = make_engine()

    with engine._lock:
        engine._speaking = True
        engine._active_file = "/tmp/amination-test.mp3"

    with patch.object(engine, "_player") as player:
        engine.cancel_current()

    player.assert_called_once_with("stop")
    assert engine._cancelled.is_set()
