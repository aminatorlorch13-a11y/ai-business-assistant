from enum import Enum
class VoiceState(Enum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    PAUSED = "paused"
    SLEEP = "sleep"
class VoiceCommand(Enum):
    STOP_SPEAKING = "stop_speaking"
    PAUSE_ACTIVITY = "pause_activity"
    SLEEP = "sleep"
    WAKE = "wake"
class VoiceSession:
    def __init__(self):
        self.state = VoiceState.IDLE
    def handle_command(self, cmd: VoiceCommand, tts_engine):
        if cmd == VoiceCommand.STOP_SPEAKING:
            tts_engine.stop()
            self.state = VoiceState.PAUSED
            return "Stopped speaking, still listening"
        elif cmd == VoiceCommand.SLEEP:
            self.state = VoiceState.SLEEP
            return "Sleeping"
        elif cmd == VoiceCommand.WAKE:
            self.state = VoiceState.LISTENING
            return "Awake"
