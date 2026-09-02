import subprocess

from app.voice.engine import SpeechEngine
from app.voice.profile import VoiceProfileResolver
from app.voice.request import SpeechRequest


class AndroidSpeechEngine(SpeechEngine):
    """
    Local Android TTS adapter using Termux.

    This adapter is intentionally limited to capabilities exposed by
    termux-tts-speak.

    Provider-specific neural voice identities belong in dedicated
    speech-engine adapters and are not interpreted here.
    """

    COMMAND = "termux-tts-speak"

    def __init__(
        self,
        profile_resolver: VoiceProfileResolver | None = None,
    ) -> None:
        self._profile_resolver = (
            profile_resolver or VoiceProfileResolver()
        )

    def speak(self, request: SpeechRequest) -> None:
        """Speak a validated speech request through Android TTS."""

        if not isinstance(request, SpeechRequest):
            raise TypeError("request must be a SpeechRequest.")

        profile = self._profile_resolver.resolve(request.voice)

        command = [self.COMMAND]

        if profile.provider is not None:
            if profile.provider != "android":
                raise ValueError(
                    "AndroidSpeechEngine cannot use a non-Android "
                    f"provider profile: '{profile.provider}'."
                )

        if profile.language is not None:
            command.extend(["-l", profile.language])

        if profile.region is not None:
            command.extend(["-n", profile.region])

        if profile.variant is not None:
            command.extend(["-v", profile.variant])

        if profile.pitch is not None:
            command.extend(["-p", str(profile.pitch)])

        effective_speed = request.speed * profile.speed

        command.extend(
            [
                "-r",
                str(effective_speed),
                request.text,
            ]
        )

        subprocess.run(
            command,
            check=True,
        )
