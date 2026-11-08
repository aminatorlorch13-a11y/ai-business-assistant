import os
import subprocess
from pathlib import Path

CONFIG = Path("deploy/forge-runner/config.sh")


def validate(**overrides):
    env = os.environ.copy()
    for key in (
        "FORGE_RUNNER_ROOT",
        "FORGE_RUNNER_HOST",
        "FORGE_RUNNER_PORT",
        "FORGE_RUNNER_IMAGE",
    ):
        env.pop(key, None)
    env.update(overrides)
    return subprocess.run(
        ["bash", "-c", 'source "$1"; forge_runner_validate_config', "_", str(CONFIG)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_default_configuration_is_valid():
    assert validate().returncode == 0


def test_custom_local_port_is_valid():
    result = validate(FORGE_RUNNER_PORT="9443")
    assert result.returncode == 0


def test_rejects_custom_data_directory():
    result = validate(FORGE_RUNNER_ROOT="/tmp/forge")
    assert result.returncode != 0


def test_rejects_public_bind_address():
    result = validate(FORGE_RUNNER_HOST="0.0.0.0")
    assert result.returncode != 0


def test_rejects_non_numeric_port():
    result = validate(FORGE_RUNNER_PORT="eighty")
    assert result.returncode != 0


def test_rejects_port_above_range():
    result = validate(FORGE_RUNNER_PORT="65536")
    assert result.returncode != 0


def test_rejects_zero_port():
    result = validate(FORGE_RUNNER_PORT="0")
    assert result.returncode != 0


def test_rejects_empty_image_name():
    result = validate(FORGE_RUNNER_IMAGE="")
    assert result.returncode != 0


def test_rejects_image_name_with_whitespace():
    result = validate(FORGE_RUNNER_IMAGE="bad image:latest")
    assert result.returncode != 0
