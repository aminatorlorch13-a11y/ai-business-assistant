import base64
import app.web.application as web_application
from datetime import datetime, timedelta, timezone

from app.assistant.message import AssistantMessage
from app.assistant.conversation import ConversationHistory, ConversationRole
from app.ai.errors import AIProviderError
from app.assistant.response import AssistantResponse
from app.commercial.trial import BusinessTrial
from app.persistence.database import SQLiteDatabase
from app.persistence.trial_repository import SQLiteTrialRepository
from app.web.application import create_app


from app.identity.models import User, BusinessMembership, UserRole
from app.auth.passwords import ScryptPasswordHasher
from app.persistence.user_repository import SQLiteUserRepository
from app.persistence.credential_repository import SQLiteCredentialRepository
from app.persistence.membership_repository import SQLiteMembershipRepository

class FakeOrchestrator:
    def __init__(self):
        self.calls = []

    def handle(
        self,
        message: AssistantMessage,
        confirmed: bool = False,
        *,
        tenant=None,
        conversation_history: ConversationHistory | None = None,
        channel: str | None = None,
        integration: str | None = None,
    ):
        self.calls.append(
            {
                "message": message,
                "confirmed": confirmed,
                "tenant": tenant,
                "conversation_history": conversation_history,
                "channel": channel,
                "integration": integration,
            }
        )
        return AssistantResponse(
            message.business_id,
            "Configured Test Assistant",
            f"Received: {message.content}",
        )


class FailingOrchestrator(FakeOrchestrator):
    def handle(self, *args, **kwargs):
        raise AIProviderError('provider API key=DO_NOT_LEAK')


def make_app(
    tmp_path,
    orchestrator_factory=FakeOrchestrator,
    speech_synthesizer=None,
):
    db = SQLiteDatabase(tmp_path / "assistant.sqlite3")
    orchestrators = []

    def runtime_builder(business):
        orchestrator = orchestrator_factory()
        orchestrators.append(orchestrator)
        return orchestrator

    app = create_app(
        database=db,
        runtime_builder=runtime_builder,
        speech_synthesizer=speech_synthesizer,
        testing=True,
    )
    app.extensions["test_orchestrators"] = orchestrators
    return app, db


def csrf(client):
    client.get("/signup")
    return client.get_cookie("assistant_csrf").value


def signup(client):
    token = csrf(client)
    response = client.post("/api/auth/signup", json={
        "display_name": "Owner", "email": "owner@example.com",
        "password": "correct horse battery staple", "business_name": "Example Business",
        "assistant_name": "Orbit", "assistant_voice": "male",
    }, headers={"X-CSRF-Token": token})
    assert response.status_code == 201


def login(client):
    token = csrf(client)
    response = client.post("/api/auth/login", json={"email": "owner@example.com", "password": "correct horse battery staple"}, headers={"X-CSRF-Token": token})
    assert response.status_code == 200


def test_signup_login_me_and_assistant_execution(tmp_path):
    app, _ = make_app(tmp_path)
    client = app.test_client()
    signup(client)
    login(client)
    payload = client.get("/api/me").get_json()
    assert payload["business"]["assistant_name"] == "Orbit"
    assert payload["commercial"]["allowed"] is True
    response = client.post("/api/assistant/message", json={"message": "read the latest message"}, headers={"X-CSRF-Token": client.get_cookie("assistant_csrf").value})
    assert response.status_code == 200
    assert response.get_json()["message"] == "Received: read the latest message"

    orchestrators = app.extensions["test_orchestrators"]
    assert len(orchestrators) == 1
    assert len(orchestrators[0].calls) == 1
    assert orchestrators[0].calls[0]["conversation_history"].turns == ()
    assert orchestrators[0].calls[0]["channel"] == "web"
    assert orchestrators[0].calls[0]["integration"] is None


def test_provider_failure_returns_safe_503_response(tmp_path):
    app, _ = make_app(tmp_path, orchestrator_factory=FailingOrchestrator)
    client = app.test_client()
    signup(client)
    login(client)

    response = client.post(
        '/api/assistant/message',
        json={'message': 'Hello'},
        headers={'X-CSRF-Token': client.get_cookie('assistant_csrf').value},
    )

    assert response.status_code == 503
    assert response.get_json() == {
        'error': 'The assistant is temporarily unavailable. '
                'Please try again shortly.'
    }
    assert 'DO_NOT_LEAK' not in response.get_data(as_text=True)


def test_owner_can_change_assistant_configuration(tmp_path):
    synthesizer = FakeSpeechSynthesizer()
    app, _ = make_app(
        tmp_path,
        speech_synthesizer=synthesizer,
    )
    client = app.test_client()
    signup(client)
    login(client)

    csrf_token = client.get_cookie("assistant_csrf").value
    response = client.post(
        "/api/business/config",
        json={
            "assistant_name": "Friday",
            "assistant_voice": "female",
        },
        headers={"X-CSRF-Token": csrf_token},
    )

    assert response.status_code == 200
    assert response.get_json()["assistant_name"] == "Friday"
    assert response.get_json()["assistant_voice"] == "female"

    saved_business = client.get("/api/me").get_json()["business"]
    assert saved_business["assistant_voice"] == "female"

    speech_response = client.post(
        "/api/assistant/message",
        json={"message": "Test the selected voice"},
        headers={"X-CSRF-Token": csrf_token},
    )

    assert speech_response.status_code == 200
    assert speech_response.get_json()["speech_available"] is True
    assert len(synthesizer.calls) == 1
    assert synthesizer.calls[0].voice == "female"

def test_expired_trial_blocks_execution_and_marks_state_expired(tmp_path):
    app, db = make_app(tmp_path)
    client = app.test_client()
    signup(client)
    login(client)
    business_id = client.get("/api/me").get_json()["business_id"]
    old_start = datetime.now(timezone.utc) - timedelta(days=8)
    SQLiteTrialRepository(db).save(BusinessTrial(business_id, old_start))
    assert client.get("/api/me").get_json()["commercial"]["status"] == "expired"
    response = client.post("/api/assistant/message", json={"message": "do work"}, headers={"X-CSRF-Token": client.get_cookie("assistant_csrf").value})
    assert response.status_code == 402



def test_logout_revokes_session_and_blocks_authenticated_requests(tmp_path):
    app, _ = make_app(tmp_path)
    client = app.test_client()

    signup(client)
    login(client)

    assert client.get("/api/me").status_code == 200

    csrf_token = client.get_cookie("assistant_csrf").value
    response = client.post(
        "/api/auth/logout",
        headers={"X-CSRF-Token": csrf_token},
    )

    assert response.status_code == 200
    assert client.get("/api/me").status_code == 401


def test_unauthenticated_assistant_execution_is_rejected(tmp_path):
    app, _ = make_app(tmp_path)
    client = app.test_client()

    csrf_token = csrf(client)
    response = client.post(
        "/api/assistant/message",
        json={"message": "do work"},
        headers={"X-CSRF-Token": csrf_token},
    )

    assert response.status_code == 401



def test_non_owner_cannot_change_assistant_configuration(tmp_path):
    app, db = make_app(tmp_path)
    owner_client = app.test_client()

    signup(owner_client)
    login(owner_client)

    owner_payload = owner_client.get("/api/me").get_json()
    business_id = owner_payload["business_id"]

    member = User(
        "member-test-user",
        "Member",
        "member@example.com",
    )

    hasher = ScryptPasswordHasher()

    SQLiteUserRepository(db).save(member)
    SQLiteCredentialRepository(db).save(
        member.user_id,
        hasher.hash("member-password"),
        at=datetime.now(timezone.utc),
    )
    SQLiteMembershipRepository(db).save(
        BusinessMembership(
            member.user_id,
            business_id,
            UserRole.MEMBER,
        )
    )

    member_client = app.test_client()
    member_csrf = csrf(member_client)

    login_response = member_client.post(
        "/api/auth/login",
        json={
            "email": "member@example.com",
            "password": "member-password",
        },
        headers={"X-CSRF-Token": member_csrf},
    )

    assert login_response.status_code == 200
    assert login_response.get_json()["business_id"] == business_id

    member_csrf = member_client.get_cookie("assistant_csrf").value

    response = member_client.post(
        "/api/business/config",
        json={
            "assistant_name": "Unauthorized",
            "assistant_voice": "female",
        },
        headers={"X-CSRF-Token": member_csrf},
    )

    assert response.status_code == 403

    # The owner configuration must remain unchanged.
    owner_payload = owner_client.get("/api/me").get_json()
    assert owner_payload["business"]["assistant_name"] == "Orbit"



def test_cross_origin_state_change_is_rejected(tmp_path):
    app, _ = make_app(tmp_path)
    client = app.test_client()
    token = csrf(client)
    response = client.post("/api/auth/login", json={"email": "owner@example.com", "password": "correct horse battery staple"}, headers={"X-CSRF-Token": token, "Origin": "https://attacker.example"})
    assert response.status_code == 403


def test_web_conversation_history_persists_between_requests(tmp_path):
    app, _ = make_app(tmp_path)
    client = app.test_client()
    signup(client)
    login(client)
    token = client.get_cookie("assistant_csrf").value

    first = client.post(
        "/api/assistant/message",
        json={"message": "My project is called Amination."},
        headers={"X-CSRF-Token": token},
    )
    second = client.post(
        "/api/assistant/message",
        json={"message": "What did I call my project?"},
        headers={"X-CSRF-Token": token},
    )

    assert first.status_code == 200
    assert second.status_code == 200

    orchestrator = app.extensions["test_orchestrators"][1]
    history = orchestrator.calls[0]["conversation_history"]

    assert [
        (turn.role, turn.content)
        for turn in history.turns
    ] == [
        (ConversationRole.USER, "My project is called Amination."),
        (ConversationRole.ASSISTANT, "Received: My project is called Amination."),
    ]


def test_provider_failure_does_not_persist_incomplete_exchange(tmp_path):
    app, _ = make_app(tmp_path, orchestrator_factory=FailingOrchestrator)
    client = app.test_client()
    signup(client)
    login(client)
    token = client.get_cookie("assistant_csrf").value

    response = client.post(
        "/api/assistant/message",
        json={"message": "Do not save an incomplete exchange."},
        headers={"X-CSRF-Token": token},
    )

    assert response.status_code == 503

    with app.extensions["assistant_database"].connection() as connection:
        row = connection.execute(
            """
            SELECT u.user_id, m.business_id
            FROM users AS u
            JOIN business_memberships AS m ON m.user_id = u.user_id
            WHERE u.email = ?
            """,
            ("owner@example.com",),
        ).fetchone()

    history = app.extensions["assistant_web_conversations"].load_history(
        user_id=row["user_id"],
        business_id=row["business_id"],
    )
    assert history.turns == ()

class FakeSpeechSynthesizer:
    def __init__(self, audio=b"test-mp3-audio"):
        self.audio = audio
        self.calls = []

    def synthesize(self, speech_request):
        self.calls.append(speech_request)
        return self.audio


class FailingSpeechSynthesizer:
    def synthesize(self, speech_request):
        raise RuntimeError("PRIVATE_PROVIDER_DETAIL")


def test_web_route_returns_injected_speech_audio_as_base64(tmp_path):
    audio_bytes = b"test-mp3-audio"
    synthesizer = FakeSpeechSynthesizer(audio=audio_bytes)

    app, _ = make_app(
        tmp_path,
        speech_synthesizer=synthesizer,
    )
    client = app.test_client()
    signup(client)
    login(client)

    response = client.post(
        "/api/assistant/message",
        json={"message": "speak this"},
        headers={
            "X-CSRF-Token": client.get_cookie("assistant_csrf").value
        },
    )

    assert response.status_code == 200
    payload = response.get_json()

    assert payload["message"] == "Received: speak this"
    assert payload["should_speak"] is True
    assert payload["speech_available"] is True
    assert payload["speech_mime_type"] == "audio/mpeg"
    assert base64.b64decode(
        payload["speech_audio_base64"],
        validate=True,
    ) == audio_bytes

    assert len(synthesizer.calls) == 1
    request = synthesizer.calls[0]
    assert request.text == "Received: speak this"
    assert request.voice == "male"
    assert request.speed == 1.0


def test_web_route_keeps_text_when_speech_provider_fails(tmp_path):
    app, _ = make_app(
        tmp_path,
        speech_synthesizer=FailingSpeechSynthesizer(),
    )
    client = app.test_client()
    signup(client)
    login(client)

    response = client.post(
        "/api/assistant/message",
        json={"message": "hello"},
        headers={
            "X-CSRF-Token": client.get_cookie("assistant_csrf").value
        },
    )

    assert response.status_code == 200
    payload = response.get_json()

    assert payload["message"] == "Received: hello"
    assert payload["should_speak"] is True
    assert payload["speech_available"] is False
    assert payload["speech_error"] == (
        "Voice playback is unavailable right now. "
        "Your text response is ready."
    )
    assert "PRIVATE_PROVIDER_DETAIL" not in response.get_data(as_text=True)
    assert "speech_audio_base64" not in payload

def test_public_root_displays_amination_landing_page(tmp_path):
    app, _ = make_app(tmp_path)
    client = app.test_client()

    response = client.get("/")

    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "Amination AI" in page
    assert 'lang="en-ZA"' in page
    assert "From Imagination" in page
    assert "to Reality." in page
    assert 'name="viewport"' in page
    assert 'property="og:title"' in page
    assert 'property="og:description"' in page
    assert 'name="twitter:card"' in page
    assert 'href="/login"' in page
    assert 'href="/signup"' in page
    assert 'href="#main-content"' in page
    assert 'id="main-content"' in page
    assert 'tabindex="-1"' in page
    assert "Skip to main content" in page
    assert '<nav class="top-nav" aria-label="Main navigation">' in page
    assert page.count("<h1>") == 1
    assert page.count('<article class="principle">') == 3
    assert '<footer class="footer">' in page


def test_authenticated_root_redirects_to_dashboard(tmp_path):
    app, _ = make_app(tmp_path)
    client = app.test_client()

    signup(client)
    login(client)

    response = client.get("/", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/dashboard")



def test_process_forge_worker_starts_once_and_registers_shutdown(monkeypatch):
    class FakeRunner:
        is_running = True

        def __init__(self):
            self.stop_calls = 0

        def stop(self):
            self.stop_calls += 1

    class FakeComposition:
        def __init__(self):
            self.calls = []
            self.runner = FakeRunner()

        def start_brain_forge_worker(self, processor, **kwargs):
            self.calls.append((processor, kwargs))
            return self.runner

    composition = FakeComposition()
    processor = object()
    registered = []

    monkeypatch.setattr(web_application, "_forge_runner", None)
    monkeypatch.setattr(
        web_application.atexit,
        "register",
        lambda callback: registered.append(callback),
    )
    monkeypatch.setenv("AMINATION_FORGE_WORKER_ENABLED", "true")

    web_application._ensure_process_forge_worker(composition, processor)
    web_application._ensure_process_forge_worker(composition, processor)

    assert len(composition.calls) == 1
    assert composition.calls[0][0] is processor
    assert composition.calls[0][1] == {
        "worker_id": f"web-forge-{web_application.os.getpid()}",
        "lease_seconds": 300,
        "poll_interval": 1.0,
    }
    assert registered == [composition.runner.stop]


def test_process_forge_worker_respects_disabled_environment(monkeypatch):
    class FakeComposition:
        def start_brain_forge_worker(self, *args, **kwargs):
            raise AssertionError("Disabled worker must not start.")

    monkeypatch.setattr(web_application, "_forge_runner", None)
    monkeypatch.setenv("AMINATION_FORGE_WORKER_ENABLED", "false")

    web_application._ensure_process_forge_worker(
        FakeComposition(),
        object(),
    )

    assert web_application._forge_runner is None


def test_process_forge_worker_restarts_if_previous_runner_stopped(monkeypatch):
    class FakeRunner:
        def __init__(self, running):
            self.is_running = running

        def stop(self):
            pass

    class FakeComposition:
        def __init__(self):
            self.runners = []

        def start_brain_forge_worker(self, *args, **kwargs):
            runner = FakeRunner(running=True)
            self.runners.append((args, kwargs, runner))
            return runner

    composition = FakeComposition()
    registered = []

    monkeypatch.setattr(
        web_application,
        "_forge_runner",
        FakeRunner(running=False),
    )
    monkeypatch.setattr(
        web_application.atexit,
        "register",
        lambda callback: registered.append(callback),
    )
    monkeypatch.setenv("AMINATION_FORGE_WORKER_ENABLED", "1")

    web_application._ensure_process_forge_worker(composition, object())

    assert len(composition.runners) == 1
    assert web_application._forge_runner is composition.runners[0][2]
    assert registered == [web_application._forge_runner.stop]


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
    return me.get_json()["business_id"]


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


def test_owner_can_immediately_cancel_own_pending_subscription(tmp_path):
    from decimal import Decimal

    app, _ = make_app(tmp_path)
    client = app.test_client()
    signup(client)
    login(client)

    business_id = client.get("/api/me").get_json()["business_id"]
    subscriptions = app.extensions["assistant_subscription_repository"]
    now = datetime.now(timezone.utc)

    subscriptions.create_plan(
        plan_id="test-plan",
        name="Test Plan",
        amount=Decimal("99.00"),
        currency="ZAR",
        interval_months=1,
        now=now,
    )
    subscriptions.create_subscription(
        subscription_id="test-subscription",
        business_id=business_id,
        plan_id="test-plan",
        now=now,
    )

    response = client.post(
        "/api/owner/subscriptions/test-subscription/cancel",
        json={"at_period_end": False},
        headers={"X-CSRF-Token": csrf(client)},
    )

    assert response.status_code == 200
    result = response.get_json()
    assert result["changed"] is True
    assert result["provider_cancellation_performed"] is False
    assert result["business_access_changed"] is False

    subscription = subscriptions.get_subscription("test-subscription")
    assert subscription["status"] == "cancelled"



def test_other_business_owner_cannot_cancel_subscription(tmp_path):
    from decimal import Decimal

    app, _ = make_app(tmp_path)
    owner_one = app.test_client()
    signup(owner_one)
    login(owner_one)

    business_one = owner_one.get("/api/me").get_json()["business_id"]
    subscriptions = app.extensions["assistant_subscription_repository"]
    now = datetime.now(timezone.utc)

    subscriptions.create_plan(
        plan_id="tenant-test-plan",
        name="Tenant Test Plan",
        amount=Decimal("99.00"),
        currency="ZAR",
        interval_months=1,
        now=now,
    )
    subscriptions.create_subscription(
        subscription_id="private-subscription",
        business_id=business_one,
        plan_id="tenant-test-plan",
        now=now,
    )

    owner_two = app.test_client()
    token = csrf(owner_two)
    signup_response = owner_two.post(
        "/api/auth/signup",
        json={
            "display_name": "Second Owner",
            "email": "second-owner@example.com",
            "password": "another correct horse battery staple",
            "business_name": "Second Business",
            "assistant_name": "Orbit Two",
            "assistant_voice": "male",
        },
        headers={"X-CSRF-Token": token},
    )
    assert signup_response.status_code == 201

    token = csrf(owner_two)
    login_response = owner_two.post(
        "/api/auth/login",
        json={
            "email": "second-owner@example.com",
            "password": "another correct horse battery staple",
        },
        headers={"X-CSRF-Token": token},
    )
    assert login_response.status_code == 200

    response = owner_two.post(
        "/api/owner/subscriptions/private-subscription/cancel",
        json={"at_period_end": False},
        headers={"X-CSRF-Token": csrf(owner_two)},
    )

    assert response.status_code == 404
    assert response.get_json() == {"error": "Subscription not found."}
    assert subscriptions.get_subscription("private-subscription")["status"] == "pending"



def test_business_member_cannot_cancel_subscription(tmp_path):
    from decimal import Decimal

    app, db = make_app(tmp_path)
    client = app.test_client()
    signup(client)
    login(client)

    business_id = client.get("/api/me").get_json()["business_id"]
    memberships = SQLiteMembershipRepository(db)
    membership = memberships.list_for_business(business_id)[0]

    memberships.save(
        BusinessMembership(
            user_id=membership.user_id,
            business_id=business_id,
            role=UserRole.MEMBER,
        )
    )

    logout_response = client.post(
        "/api/auth/logout",
        headers={"X-CSRF-Token": csrf(client)},
    )
    assert logout_response.status_code == 200
    login(client)

    subscriptions = app.extensions["assistant_subscription_repository"]
    now = datetime.now(timezone.utc)

    subscriptions.create_plan(
        plan_id="member-test-plan",
        name="Member Test Plan",
        amount=Decimal("99.00"),
        currency="ZAR",
        interval_months=1,
        now=now,
    )
    subscriptions.create_subscription(
        subscription_id="member-private-subscription",
        business_id=business_id,
        plan_id="member-test-plan",
        now=now,
    )

    response = client.post(
        "/api/owner/subscriptions/member-private-subscription/cancel",
        json={"at_period_end": False},
        headers={"X-CSRF-Token": csrf(client)},
    )

    assert response.status_code == 403
    assert response.get_json() == {
        "error": "Only the business owner may cancel a subscription."
    }
    assert subscriptions.get_subscription(
        "member-private-subscription"
    )["status"] == "pending"

