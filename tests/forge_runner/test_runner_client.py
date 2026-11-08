import pytest

from app.forge.runner.client import ForgeRunnerClient


def test_remote_runner_requires_https():
    with pytest.raises(ValueError):
        ForgeRunnerClient("http://runner.example.com", "secret")


def test_local_runner_allows_http():
    client = ForgeRunnerClient("http://127.0.0.1:8765", "secret")
    assert client.base_url == "http://127.0.0.1:8765"


def test_runner_requires_authentication_token():
    with pytest.raises(ValueError):
        ForgeRunnerClient("https://runner.example.com", "")


def test_invalid_session_ids_are_rejected():
    client = ForgeRunnerClient("https://runner.example.com", "secret")

    with pytest.raises(ValueError):
        client.execute("../other", "pwd")

    with pytest.raises(ValueError):
        client.read_files("invalid-session")

    with pytest.raises(ValueError):
        client.close_session("invalid-session")
