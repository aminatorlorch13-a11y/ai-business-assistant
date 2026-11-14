from pathlib import Path

app_path = Path("app/web/application.py")
test_path = Path("tests/test_web_application.py")

app_source = app_path.read_text()
test_source = test_path.read_text()

# 1. Separate database-backed composition lookup from runner-backed service creation.
start_marker = "    def _forge_terminal_service():"
end_marker = "    def _forge_terminal_identity():"

if start_marker not in app_source or end_marker not in app_source:
    raise SystemExit("Could not locate the Forge terminal factory boundaries. No files changed.")

start = app_source.index(start_marker)
end = app_source.index(end_marker, start)

replacement = '''    def _forge_terminal_composition():
        composition = app.extensions.get("assistant_capability_composition")
        if composition is None:
            composition = build_production_capability_composition(
                database=app.extensions["assistant_database"],
            )
            app.extensions["assistant_capability_composition"] = composition
        return composition

    def _forge_terminal_service():
        service = app.extensions.get("assistant_forge_terminal_service")
        if service is not None:
            return service

        # Runner configuration is needed only when a terminal is opened.
        composition = _forge_terminal_composition()
        service = composition.create_forge_terminal_service()
        app.extensions["assistant_forge_terminal_service"] = service
        return service

'''

app_source = app_source[:start] + replacement + app_source[end:]

old_list_factory = '''        # Reuse the composition and database already owned by this Flask app.
        _forge_terminal_service()
        composition = app.extensions.get("assistant_capability_composition")
'''
new_list_factory = '''        # Project discovery must not depend on remote runner configuration.
        composition = _forge_terminal_composition()
'''

if old_list_factory not in app_source:
    raise SystemExit(
        "Could not locate the project-list service coupling. "
        "No application or test files changed."
    )

app_source = app_source.replace(old_list_factory, new_list_factory, 1)

# 2. Add route-level security tests to the existing web test module.
marker = "def test_forge_terminal_project_list_is_business_scoped"
if marker not in test_source:
    test_additions = r'''

def _forge_test_create_logged_in_business(client, email, business_name):
    token = csrf(client)
    response = client.post(
        "/api/auth/signup",
        json={
            "display_name": "Forge Test Owner",
            "email": email,
            "password": "correct horse battery staple",
            "business_name": business_name,
            "assistant_name": "Forge Test Assistant",
            "assistant_voice": "male",
        },
        headers={"X-CSRF-Token": token},
    )
    assert response.status_code == 201, response.get_data(as_text=True)

    token = client.get_cookie("assistant_csrf").value
    response = client.post(
        "/api/auth/login",
        json={
            "email": email,
            "password": "correct horse battery staple",
        },
        headers={"X-CSRF-Token": token},
    )
    assert response.status_code == 200, response.get_data(as_text=True)

    me = client.get("/api/me")
    assert me.status_code == 200
    return me.get_json()["business"]["business_id"]


def test_forge_terminal_project_list_is_business_scoped(
    tmp_path, monkeypatch
):
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from app.forge.project_store import ForgeProjectStore

    app, database = make_app(tmp_path)
    owner_client = app.test_client()
    other_client = app.test_client()

    owner_business = _forge_test_create_logged_in_business(
        owner_client, "forge-owner@example.com", "Forge Owner Business"
    )
    other_business = _forge_test_create_logged_in_business(
        other_client, "forge-other@example.com", "Forge Other Business"
    )
    assert owner_business != other_business

    # Both businesses deliberately use the same project ID.
    projects = ForgeProjectStore(database)
    projects.create(owner_business, "shared-project", "Owner project")
    projects.create(other_business, "shared-project", "Other project")

    def job_record(job_id, status):
        return SimpleNamespace(
            job=SimpleNamespace(
                job_id=job_id,
                status=status,
                job_type="code_review",
                phase="completed",
                created_at=datetime.now(timezone.utc),
            )
        )

    class FakeJobStore:
        def list_for_project(self, business_id, project_id):
            assert project_id == "shared-project"
            return {
                owner_business: [
                    job_record("owner-job", "completed_vaulted"),
                    job_record("owner-locked-job", "completed_vaulted_locked"),
                    job_record("owner-failed-job", "failed"),
                ],
                other_business: [
                    job_record("other-job", "completed_vaulted"),
                ],
            }.get(business_id, [])

    class FakeComposition:
        forge_job_store = FakeJobStore()

        def create_forge_terminal_service(self):
            raise AssertionError(
                "Project discovery must not construct a runner-backed terminal service."
            )

    app.extensions["assistant_capability_composition"] = FakeComposition()

    # A partial runner configuration must not break project discovery.
    monkeypatch.setenv("FORGE_RUNNER_URL", "https://runner.example.invalid")
    monkeypatch.delenv("FORGE_RUNNER_TOKEN", raising=False)

    response = owner_client.get("/api/forge/terminal/projects")
    assert response.status_code == 200, response.get_data(as_text=True)

    payload = response.get_json()
    assert payload["ok"] is True
    assert len(payload["projects"]) == 1

    project = payload["projects"][0]
    assert project["project_id"] == "shared-project"
    assert project["name"] == "Owner project"
    assert [job["job_id"] for job in project["jobs"]] == ["owner-job"]


def test_forge_terminal_open_enforces_authenticated_business_scope(tmp_path):
    app, _ = make_app(tmp_path)
    owner_client = app.test_client()
    other_client = app.test_client()

    owner_business = _forge_test_create_logged_in_business(
        owner_client, "forge-scope-owner@example.com", "Scope Owner Business"
    )
    other_business = _forge_test_create_logged_in_business(
        other_client, "forge-scope-other@example.com", "Scope Other Business"
    )
    assert owner_business != other_business

    class ScopedTerminalService:
        def __init__(self):
            self.calls = []

        def open_session(self, business_id, project_id, job_id):
            self.calls.append((business_id, project_id, job_id))
            if (business_id, project_id, job_id) != (
                other_business, "same-project", "same-job"
            ):
                raise PermissionError("Terminal session is not available.")
            return {"opened": True}

    service = ScopedTerminalService()
    app.extensions["assistant_forge_terminal_service"] = service

    path = (
        "/api/forge/projects/same-project/jobs/same-job/terminal"
    )

    # CSRF is required before the terminal operation is reached.
    missing_csrf = owner_client.post(path)
    assert missing_csrf.status_code == 403
    assert service.calls == []

    owner_token = owner_client.get_cookie("assistant_csrf").value
    denied = owner_client.post(
        path, headers={"X-CSRF-Token": owner_token}
    )
    assert denied.status_code == 403

    other_token = other_client.get_cookie("assistant_csrf").value
    allowed = other_client.post(
        path, headers={"X-CSRF-Token": other_token}
    )
    assert allowed.status_code == 200
    assert allowed.get_json()["terminal"]["opened"] is True

    # The route always passes the authenticated business, never a client-supplied one.
    assert service.calls == [
        (owner_business, "same-project", "same-job"),
        (other_business, "same-project", "same-job"),
    ]

'''
    test_source += test_additions

# Write only after all expected patch locations have been verified.
app_path.write_text(app_source)
test_path.write_text(test_source)

print("Forge terminal security patch installed.")
print("- Runner-independent project discovery")
print("- Business-scoped project/job listing test")
print("- Locked and failed job filtering test")
print("- CSRF and cross-business terminal-open tests")
