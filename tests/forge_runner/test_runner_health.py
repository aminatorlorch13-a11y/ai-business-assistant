import subprocess

from app.forge.runner import server


def test_health_is_ready_when_docker_and_image_are_available(monkeypatch):
    calls = []
    results = iter([
        subprocess.CompletedProcess(["docker", "info"], 0),
        subprocess.CompletedProcess(["docker", "image", "inspect"], 0),
    ])

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return next(results)

    monkeypatch.setattr(server.subprocess, "run", fake_run)

    status, payload = server._health_status()

    assert status == 200
    assert payload == {
        "status": "ready",
        "docker_available": True,
        "image_available": True,
    }
    assert len(calls) == 2
    assert all(call[1]["shell"] is False for call in calls)


def test_health_is_degraded_when_docker_is_unavailable(monkeypatch):
    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(args, 1)

    monkeypatch.setattr(server.subprocess, "run", fake_run)

    status, payload = server._health_status()

    assert status == 503
    assert payload["status"] == "degraded"
    assert payload["docker_available"] is False
    assert payload["image_available"] is False


def test_health_is_degraded_when_runner_image_is_missing(monkeypatch):
    results = iter([
        subprocess.CompletedProcess(["docker", "info"], 0),
        subprocess.CompletedProcess(["docker", "image", "inspect"], 1),
    ])

    monkeypatch.setattr(
        server.subprocess,
        "run",
        lambda *args, **kwargs: next(results),
    )

    status, payload = server._health_status()

    assert status == 503
    assert payload["docker_available"] is True
    assert payload["image_available"] is False


def test_health_handles_missing_docker_binary(monkeypatch):
    def fake_run(*args, **kwargs):
        raise FileNotFoundError("docker")

    monkeypatch.setattr(server.subprocess, "run", fake_run)

    status, payload = server._health_status()

    assert status == 503
    assert payload["docker_available"] is False
    assert payload["image_available"] is False
