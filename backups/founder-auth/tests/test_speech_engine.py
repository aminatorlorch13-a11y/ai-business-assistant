from unittest.mock import patch

import pytest

from app.voice.local_engine import AndroidSpeechEngine
from app.voice.profile import VoiceProfile, VoiceProfileResolver
from app.voice.request import SpeechRequest


def test_android_speech_engine_speaks_with_default_female_profile():
    engine = AndroidSpeechEngine()

    request = SpeechRequest(
        text="The assistant is ready.",
        voice="female",
        speed=1.0,
    )

    with patch("subprocess.Popen") as run:
        engine.speak(request)

    run.assert_called_once_with(
        [
            "termux-tts-speak",
            "-r",
            "1.0",
            "The assistant is ready.",
        ],
    )


def test_android_speech_engine_speaks_with_default_male_profile():
    engine = AndroidSpeechEngine()

    request = SpeechRequest(
        text="The assistant is ready.",
        voice="male",
        speed=1.0,
    )

    with patch("subprocess.Popen") as run:
        engine.speak(request)

    run.assert_called_once_with(
        [
            "termux-tts-speak",
            "-r",
            "1.0",
            "The assistant is ready.",
        ],
    )


def test_android_speech_engine_does_not_fake_voice_identity_with_pitch():
    engine = AndroidSpeechEngine()

    female_request = SpeechRequest(
        text="Hello.",
        voice="female",
        speed=1.0,
    )

    male_request = SpeechRequest(
        text="Hello.",
        voice="male",
        speed=1.0,
    )

    with patch("subprocess.Popen") as run:
        engine.speak(female_request)
        engine.speak(male_request)

    assert run.call_count == 2

    female_command = run.call_args_list[0].args[0]
    male_command = run.call_args_list[1].args[0]

    assert "-p" not in female_command
    assert "-p" not in male_command


def test_android_speech_engine_passes_custom_speed():
    engine = AndroidSpeechEngine()

    request = SpeechRequest(
        text="Speak more slowly.",
        voice="female",
        speed=0.75,
    )

    with patch("subprocess.Popen") as run:
        engine.speak(request)

    run.assert_called_once_with(
        [
            "termux-tts-speak",
            "-r",
            "0.75",
            "Speak more slowly.",
        ],
    )


def test_android_speech_engine_combines_profile_speed_with_request_speed():
    resolver = VoiceProfileResolver(
        {
            "female": VoiceProfile(
                voice="female",
                speed=0.8,
            ),
        }
    )

    engine = AndroidSpeechEngine(resolver)

    request = SpeechRequest(
        text="Combined speed.",
        voice="female",
        speed=0.75,
    )

    with patch("subprocess.Popen") as run:
        engine.speak(request)

    run.assert_called_once_with(
        [
            "termux-tts-speak",
            "-r",
            "0.6000000000000001",
            "Combined speed.",
        ],
    )


def test_android_speech_engine_passes_language():
    resolver = VoiceProfileResolver(
        {
            "female": VoiceProfile(
                voice="female",
                provider="android",
                language="en",
            ),
        }
    )

    engine = AndroidSpeechEngine(resolver)

    request = SpeechRequest(
        text="Hello.",
        voice="female",
        speed=1.0,
    )

    with patch("subprocess.Popen") as run:
        engine.speak(request)

    run.assert_called_once_with(
        [
            "termux-tts-speak",
            "-l",
            "en",
            "-r",
            "1.0",
            "Hello.",
        ],
    )


def test_android_speech_engine_passes_region():
    resolver = VoiceProfileResolver(
        {
            "female": VoiceProfile(
                voice="female",
                provider="android",
                region="ZA",
            ),
        }
    )

    engine = AndroidSpeechEngine(resolver)

    request = SpeechRequest(
        text="Hello.",
        voice="female",
        speed=1.0,
    )

    with patch("subprocess.Popen") as run:
        engine.speak(request)

    run.assert_called_once_with(
        [
            "termux-tts-speak",
            "-n",
            "ZA",
            "-r",
            "1.0",
            "Hello.",
        ],
    )


def test_android_speech_engine_passes_variant():
    resolver = VoiceProfileResolver(
        {
            "female": VoiceProfile(
                voice="female",
                provider="android",
                variant="default",
            ),
        }
    )

    engine = AndroidSpeechEngine(resolver)

    request = SpeechRequest(
        text="Hello.",
        voice="female",
        speed=1.0,
    )

    with patch("subprocess.Popen") as run:
        engine.speak(request)

    run.assert_called_once_with(
        [
            "termux-tts-speak",
            "-v",
            "default",
            "-r",
            "1.0",
            "Hello.",
        ],
    )


def test_android_speech_engine_passes_android_provider_options():
    resolver = VoiceProfileResolver(
        {
            "female": VoiceProfile(
                voice="female",
                provider="android",
                language="en",
                region="ZA",
                variant="default",
            ),
        }
    )

    engine = AndroidSpeechEngine(resolver)

    request = SpeechRequest(
        text="The assistant is ready.",
        voice="female",
        speed=1.0,
    )

    with patch("subprocess.Popen") as run:
        engine.speak(request)

    run.assert_called_once_with(
        [
            "termux-tts-speak",
            "-l",
            "en",
            "-n",
            "ZA",
            "-v",
            "default",
            "-r",
            "1.0",
            "The assistant is ready.",
        ],
    )


def test_android_speech_engine_rejects_non_android_provider():
    resolver = VoiceProfileResolver(
        {
            "female": VoiceProfile(
                voice="female",
                provider="neural-provider",
                provider_voice_id="female-001",
            ),
        }
    )

    engine = AndroidSpeechEngine(resolver)

    request = SpeechRequest(
        text="Hello.",
        voice="female",
        speed=1.0,
    )

    with patch("subprocess.Popen") as run:
        with pytest.raises(
            ValueError,
            match="cannot use a non-Android provider profile",
        ):
            engine.speak(request)

    run.assert_not_called()


def test_android_speech_engine_does_not_interpret_provider_voice_id():
    resolver = VoiceProfileResolver(
        {
            "female": VoiceProfile(
                voice="female",
                provider="android",
                provider_voice_id="android-voice-001",
            ),
        }
    )

    engine = AndroidSpeechEngine(resolver)

    request = SpeechRequest(
        text="Hello.",
        voice="female",
        speed=1.0,
    )

    with patch("subprocess.Popen") as run:
        engine.speak(request)

    command = run.call_args.args[0]

    assert "android-voice-001" not in command


def test_android_speech_engine_rejects_invalid_request():
    engine = AndroidSpeechEngine()

    with patch("subprocess.Popen") as run:
        with pytest.raises(
            TypeError,
            match="SpeechRequest",
        ):
            engine.speak("not a request")

    run.assert_not_called()


def test_android_speech_engine_rejects_unconfigured_voice():
    engine = AndroidSpeechEngine()

    request = SpeechRequest(
        text="Hello.",
        voice="female",
        speed=1.0,
    )

    resolver = VoiceProfileResolver(
        {
            "male": VoiceProfile(
                voice="male",
            ),
        }
    )

    engine = AndroidSpeechEngine(resolver)

    with patch("subprocess.Popen") as run:
        with pytest.raises(
            ValueError,
            match="No voice profile configured",
        ):
            engine.speak(request)

    run.assert_not_called()


def test_android_speech_engine_propagates_subprocess_failure():
    engine = AndroidSpeechEngine()

    request = SpeechRequest(
        text="This should fail.",
        voice="male",
        speed=1.0,
    )

    with patch(
        "subprocess.Popen",
        side_effect=RuntimeError("tts failure"),
    ) as run:
        with pytest.raises(
            RuntimeError,
            match="tts failure",
        ):
            engine.speak(request)

    run.assert_called_once()


def test_android_speech_engine_uses_configured_pitch_when_explicitly_requested():
    resolver = VoiceProfileResolver(
        {
            "male": VoiceProfile(
                voice="male",
                provider="android",
                pitch=0.95,
            ),
        }
    )

    engine = AndroidSpeechEngine(resolver)

    request = SpeechRequest(
        text="Configured pitch.",
        voice="male",
        speed=1.0,
    )

    with patch("subprocess.Popen") as run:
        engine.speak(request)

    run.assert_called_once_with(
        [
            "termux-tts-speak",
            "-p",
            "0.95",
            "-r",
            "1.0",
            "Configured pitch.",
        ],
    )


def test_android_speech_engine_preserves_request_text_exactly():
    engine = AndroidSpeechEngine()

    text = "Hello, this is a test: 100% ready!"

    request = SpeechRequest(
        text=text,
        voice="female",
        speed=1.0,
    )

    with patch("subprocess.Popen") as run:
        engine.speak(request)

    command = run.call_args.args[0]

    assert command[-1] == text
