import base64
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
