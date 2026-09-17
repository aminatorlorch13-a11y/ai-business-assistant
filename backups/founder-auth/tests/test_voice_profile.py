import math

import pytest

from app.voice.profile import (
    DEFAULT_VOICE_PROFILES,
    VoiceProfile,
    VoiceProfileResolver,
)


def test_default_profiles_are_configured_logical_voices():
    assert set(DEFAULT_VOICE_PROFILES) == {"male", "female"}

    assert DEFAULT_VOICE_PROFILES["male"].voice == "male"
    assert DEFAULT_VOICE_PROFILES["female"].voice == "female"


def test_default_profiles_do_not_fake_voice_identity_with_pitch():
    assert DEFAULT_VOICE_PROFILES["male"].pitch is None
    assert DEFAULT_VOICE_PROFILES["female"].pitch is None


def test_default_profiles_have_no_provider_assumption():
    assert DEFAULT_VOICE_PROFILES["male"].provider is None
    assert DEFAULT_VOICE_PROFILES["female"].provider is None

    assert DEFAULT_VOICE_PROFILES["male"].provider_voice_id is None
    assert DEFAULT_VOICE_PROFILES["female"].provider_voice_id is None


def test_voice_profile_accepts_valid_configuration():
    profile = VoiceProfile(
        voice="male",
        provider="neural-provider",
        provider_voice_id="male-voice-001",
        pitch=0.95,
        speed=1.1,
        language="en",
        region="ZA",
        variant="conversational",
    )

    assert profile.voice == "male"
    assert profile.provider == "neural-provider"
    assert profile.provider_voice_id == "male-voice-001"
    assert profile.pitch == 0.95
    assert profile.speed == 1.1
    assert profile.language == "en"
    assert profile.region == "ZA"
    assert profile.variant == "conversational"


def test_voice_profile_accepts_provider_without_provider_voice_id():
    profile = VoiceProfile(
        voice="male",
        provider="android",
    )

    assert profile.provider == "android"
    assert profile.provider_voice_id is None


def test_voice_profile_accepts_profile_without_provider():
    profile = VoiceProfile(
        voice="female",
    )

    assert profile.provider is None
    assert profile.provider_voice_id is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"voice": ""},
        {"voice": "   "},
        {"voice": 123},
        {"voice": None},
        {"voice": "male", "provider": ""},
        {"voice": "male", "provider": "   "},
        {"voice": "male", "provider_voice_id": ""},
        {"voice": "male", "provider_voice_id": "   "},
        {"voice": "male", "pitch": 0},
        {"voice": "male", "pitch": -1},
        {"voice": "male", "pitch": float("inf")},
        {"voice": "male", "pitch": float("-inf")},
        {"voice": "male", "pitch": float("nan")},
        {"voice": "male", "pitch": True},
        {"voice": "male", "pitch": "1.0"},
        {"voice": "male", "speed": 0},
        {"voice": "male", "speed": -1},
        {"voice": "male", "speed": float("inf")},
        {"voice": "male", "speed": float("-inf")},
        {"voice": "male", "speed": float("nan")},
        {"voice": "male", "speed": True},
        {"voice": "male", "speed": "1.0"},
        {"voice": "male", "language": ""},
        {"voice": "male", "language": "   "},
        {"voice": "male", "region": ""},
        {"voice": "male", "region": "   "},
        {"voice": "male", "variant": ""},
        {"voice": "male", "variant": "   "},
        {"voice": "male", "provider_voice_id": "voice-001"},
    ],
)
def test_voice_profile_rejects_invalid_configuration(kwargs):
    with pytest.raises(ValueError):
        VoiceProfile(**kwargs)


def test_voice_profile_is_immutable():
    profile = VoiceProfile(voice="male")

    with pytest.raises(Exception):
        profile.voice = "female"


def test_resolver_uses_default_profiles():
    resolver = VoiceProfileResolver()

    male = resolver.resolve("male")
    female = resolver.resolve("female")

    assert male == DEFAULT_VOICE_PROFILES["male"]
    assert female == DEFAULT_VOICE_PROFILES["female"]


def test_resolver_returns_configured_profile():
    profile = VoiceProfile(
        voice="male",
        provider="neural-provider",
        provider_voice_id="male-123",
    )

    resolver = VoiceProfileResolver(
        {
            "male": profile,
        }
    )

    assert resolver.resolve("male") is profile


def test_resolver_copies_mapping():
    profile = VoiceProfile(voice="male")

    profiles = {
        "male": profile,
    }

    resolver = VoiceProfileResolver(profiles)

    profiles["female"] = VoiceProfile(voice="female")

    with pytest.raises(ValueError):
        resolver.resolve("female")

    assert resolver.resolve("male") is profile


def test_resolver_rejects_non_mapping():
    with pytest.raises(TypeError, match="mapping"):
        VoiceProfileResolver([])


def test_resolver_rejects_non_string_profile_name():
    profile = VoiceProfile(voice="male")

    with pytest.raises(ValueError, match="profile names"):
        VoiceProfileResolver(
            {
                123: profile,
            }
        )


def test_resolver_rejects_empty_profile_name():
    profile = VoiceProfile(voice="male")

    with pytest.raises(ValueError, match="profile names"):
        VoiceProfileResolver(
            {
                "": profile,
            }
        )


def test_resolver_rejects_non_voice_profile_values():
    with pytest.raises(TypeError, match="VoiceProfile"):
        VoiceProfileResolver(
            {
                "male": object(),
            }
        )


def test_resolver_rejects_mismatched_profile_name():
    profile = VoiceProfile(voice="female")

    with pytest.raises(
        ValueError,
        match="profile name must match VoiceProfile.voice",
    ):
        VoiceProfileResolver(
            {
                "male": profile,
            }
        )


@pytest.mark.parametrize(
    "voice",
    [
        "",
        "   ",
        None,
        123,
    ],
)
def test_resolver_rejects_invalid_voice_lookup(voice):
    resolver = VoiceProfileResolver()

    with pytest.raises(ValueError):
        resolver.resolve(voice)


def test_resolver_rejects_unknown_voice():
    resolver = VoiceProfileResolver()

    with pytest.raises(
        ValueError,
        match="No voice profile configured",
    ):
        resolver.resolve("robot")


def test_voice_profile_speed_and_pitch_are_finite_when_present():
    profile = VoiceProfile(
        voice="male",
        pitch=1.0,
        speed=1.0,
    )

    assert math.isfinite(profile.pitch)
    assert math.isfinite(profile.speed)
