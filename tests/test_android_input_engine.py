import subprocess
from unittest.mock import patch

import pytest

from app.voice.android_input_engine import AndroidSpeechInputEngine
from app.voice.speech_input import SpeechInput


def test_android_input_engine_returns_speech_input():
    engine = AndroidSpeechInputEngine()

    completed = subprocess.CompletedProcess(
        args=["termux-speech-to-text"],
        returncode=0,
        stdout="  Hello, this is a test.  \n",
        stderr="",
    )

    with patch("subprocess.run", return_value=completed) as run:
        result = engine.listen()

    assert isinstance(result, SpeechInput)
    assert result.text == "Hello, this is a test."

    run.assert_called_once_with(
        ["termux-speech-to-text"],
        check=True,
        capture_output=True,
        text=True,
    )


def test_android_input_engine_rejects_empty_output():
    engine = AndroidSpeechInputEngine()

    completed = subprocess.CompletedProcess(
        args=["termux-speech-to-text"],
        returncode=0,
        stdout="",
        stderr="",
    )

    with patch("subprocess.run", return_value=completed):
        with pytest.raises(
            RuntimeError,
            match="no usable text",
        ):
            engine.listen()


def test_android_input_engine_rejects_whitespace_output():
    engine = AndroidSpeechInputEngine()

    completed = subprocess.CompletedProcess(
        args=["termux-speech-to-text"],
        returncode=0,
        stdout="   \n\t",
        stderr="",
    )

    with patch("subprocess.run", return_value=completed):
        with pytest.raises(
            RuntimeError,
            match="no usable text",
        ):
            engine.listen()


def test_android_input_engine_wraps_stt_failure():
    engine = AndroidSpeechInputEngine()

    error = subprocess.CalledProcessError(
        returncode=1,
        cmd=["termux-speech-to-text"],
    )

    with patch("subprocess.run", side_effect=error):
        with pytest.raises(
            RuntimeError,
            match="speech recognition failed",
        ):
            engine.listen()


def test_android_input_engine_wraps_missing_command():
    engine = AndroidSpeechInputEngine()

    error = OSError("command not found")

    with patch("subprocess.run", side_effect=error):
        with pytest.raises(
            RuntimeError,
            match="command is unavailable",
        ):
            engine.listen()


def test_android_input_engine_exposes_fixed_command():
    assert (
        AndroidSpeechInputEngine.COMMAND
        == "termux-speech-to-text"
    )
