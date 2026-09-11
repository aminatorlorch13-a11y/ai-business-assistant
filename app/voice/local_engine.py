import subprocess
import threading

from app.voice.engine import SpeechEngine
from app.voice.profile import VoiceProfileResolver
from app.voice.request import SpeechRequest


class AndroidSpeechEngine(SpeechEngine):
    """
    Local Android TTS adapter using Termux.

    The active Termux TTS process is retained so speech output can be
    explicitly cancelled without terminating the conversation session.

    Active-process ownership is protected by a lock so concurrent
    cancellation cannot terminate the same process more than once and
    cannot accidentally clear a newer process reference.
    """

    COMMAND = "termux-tts-speak"

    def __init__(
        self,
        profile_resolver: VoiceProfileResolver | None = None,
    ) -> None:
        self._profile_resolver = (
            profile_resolver or VoiceProfileResolver()
        )
        self._active_process = None
        self._process_lock = threading.Lock()

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

        # Process creation and publication of the active-process reference
        # are one atomic operation from the cancellation boundary's point
        # of view. This prevents cancellation from observing a gap between
        # Popen() and assignment to _active_process.
        with self._process_lock:
            active = self._active_process

            if active is not None:
                if active.poll() is None:
                    raise RuntimeError(
                        "AndroidSpeechEngine already has active speech."
                    )

                self._active_process = None

            process = subprocess.Popen(command)
            self._active_process = process

        try:
            process.wait()
        finally:
            # Only the operation that owns this exact process may clear
            # the active reference. A newer speech operation is preserved.
            with self._process_lock:
                if self._active_process is process:
                    self._active_process = None

    def cancel_current(self) -> None:
        """
        Cancel only the currently active TTS process.

        This does not modify conversation/session state.

        Process ownership is claimed atomically under the lock. Once
        claimed, the process reference is removed from the active slot
        before termination begins, preventing another cancellation call
        from terminating the same process.
        """

        with self._process_lock:
            process = self._active_process

            if process is None:
                return

            # Claim this process exclusively.
            self._active_process = None

        try:
            if process.poll() is not None:
                return

            try:
                process.terminate()
            except ProcessLookupError:
                # The process disappeared between poll() and terminate().
                # It is already effectively finished.
                pass
        finally:
            # Do not touch _active_process here. A newer speech operation
            # may already own that slot.
            pass
