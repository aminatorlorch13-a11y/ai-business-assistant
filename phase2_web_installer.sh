#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

cd "$HOME/ai-business-assistant"

# Phase 2 installs the customer-facing web boundary on top of the existing
# architecture. It deliberately refuses to run against an unexpected tree.
[[ -f app/auth/service.py ]] || { echo "Missing Step 1 auth foundation."; exit 1; }
[[ -f app/auth/signup.py ]] || { echo "Missing Step 1 signup transaction."; exit 1; }
[[ -f app/persistence/business_repository.py ]] || { echo "Missing business repository."; exit 1; }
[[ -f app/persistence/commercial_state_repository.py ]] || { echo "Missing commercial state repository."; exit 1; }
[[ -f app/cli/assistant_factory.py ]] || { echo "Missing assistant factory."; exit 1; }
[[ -f requirements.txt ]] || { echo "Missing requirements.txt."; exit 1; }
grep -q '^Flask==3\.1\.3$' requirements.txt || { echo "Expected Flask 3.1.3 dependency was not found."; exit 1; }
grep -q 'def build_orchestrator_for_business' app/cli/assistant_factory.py || { echo "Expected business-scoped orchestrator factory was not found."; exit 1; }

STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP=".phase2_web_backup_${STAMP}"
mkdir -p "$BACKUP/app" "$BACKUP/tests"

backup_if_exists() {
  local file="$1"
  if [[ -e "$file" ]]; then
    mkdir -p "$BACKUP/$(dirname "$file")"
    cp -a "$file" "$BACKUP/$file"
  fi
}

for file in \
  app/web/__init__.py \
  app/web/application.py \
  app/web/auth.py \
  app/web/access.py \
  app/web/security.py \
  app/web/templates/login.html \
  app/web/templates/signup.html \
  app/web/templates/dashboard.html \
  app/web/static/app.css \
  app/web/static/app.js \
  run_web.py \
  tests/test_web_application.py
 do
  backup_if_exists "$file"
done

mkdir -p app/web/templates app/web/static

cat > app/web/access.py <<'PY'
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.commercial.state import CommercialStatus, BusinessCommercialState
from app.commercial.trial import BusinessTrial
from app.persistence.commercial_state_repository import SQLiteCommercialStateRepository
from app.persistence.database import SQLiteDatabase
from app.persistence.trial_repository import SQLiteTrialRepository


class BusinessAccessDenied(PermissionError):
    """The business is not currently entitled to execute assistant work."""


@dataclass(frozen=True)
class BusinessAccess:
    business_id: str
    status: CommercialStatus
    allowed: bool
    reason: str
    trial_ends_at: datetime | None = None


class BusinessAccessService:
    """Resolve commercial execution access without mixing it into auth or UI."""

    def __init__(self, database: SQLiteDatabase, clock=datetime.now) -> None:
        self._states = SQLiteCommercialStateRepository(database)
        self._trials = SQLiteTrialRepository(database)
        self._clock = clock

    def resolve(self, business_id: str) -> BusinessAccess:
        state = self._states.get(business_id)
        if state is None:
            raise BusinessAccessDenied("Business commercial state is missing.")

        now = _aware_utc(self._clock)
        trial = self._trials.get(business_id)

        if state.status == CommercialStatus.TRIAL:
            if trial is None:
                self._states.save(
                    BusinessCommercialState(business_id, CommercialStatus.EXPIRED)
                )
                return BusinessAccess(
                    business_id, CommercialStatus.EXPIRED, False,
                    "Trial information is missing.", None,
                )
            if trial.is_expired(now):
                self._states.save(
                    BusinessCommercialState(business_id, CommercialStatus.EXPIRED)
                )
                return BusinessAccess(
                    business_id, CommercialStatus.EXPIRED, False,
                    "The trial has expired.", trial.ends_at,
                )
            return BusinessAccess(
                business_id, CommercialStatus.TRIAL, True,
                "Trial access is active.", trial.ends_at,
            )

        if state.status == CommercialStatus.ACTIVE:
            return BusinessAccess(
                business_id, CommercialStatus.ACTIVE, True,
                "Business access is active.",
                trial.ends_at if trial else None,
            )

        return BusinessAccess(
            business_id,
            state.status,
            False,
            "Business execution access is suspended.",
            trial.ends_at if trial else None,
        )

    def require_execution(self, business_id: str) -> BusinessAccess:
        access = self.resolve(business_id)
        if not access.allowed:
            raise BusinessAccessDenied(access.reason)
        return access


def _aware_utc(clock) -> datetime:
    try:
        value = clock(timezone.utc)
    except TypeError:
        value = clock()
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
PY

cat > app/web/security.py <<'PY'
from __future__ import annotations

from urllib.parse import urlparse

from flask import Request


class WebSecurityError(PermissionError):
    """A browser request failed a web security boundary."""


def require_same_origin(request: Request) -> None:
    """Reject cross-origin state-changing browser requests."""
    origin = request.headers.get("Origin")
    referer = request.headers.get("Referer")
    candidate = origin or referer
    if not candidate:
        return

    parsed = urlparse(candidate)
    expected = request.host_url.rstrip("/")
    actual = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    if actual != expected:
        raise WebSecurityError("Cross-origin request rejected.")
PY

cat > app/web/auth.py <<'PY'
from __future__ import annotations

from functools import wraps
import secrets

from flask import g, jsonify, request

from app.auth.errors import SessionInvalid
from app.auth.service import AuthenticationService
from app.web.security import require_same_origin

SESSION_COOKIE = "assistant_session"
CSRF_COOKIE = "assistant_csrf"


def install_auth_hooks(app, auth_service: AuthenticationService) -> None:
    app.extensions["assistant_auth"] = auth_service

    @app.before_request
    def load_principal():
        token = request.cookies.get(SESSION_COOKIE)
        g.principal = None
        if not token:
            return None
        try:
            g.principal = auth_service.validate_session(token, source_key="web")
        except SessionInvalid:
            if request.path.startswith("/api/"):
                response = jsonify({"error": "Authentication required."})
                response.delete_cookie(SESSION_COOKIE, path="/")
                response.delete_cookie(CSRF_COOKIE, path="/")
                return response, 401
            g.principal = None
        return None


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        principal = getattr(g, "principal", None)
        if principal is None:
            return jsonify({"error": "Authentication required."}), 401
        return view(*args, **kwargs)

    return wrapped


def issue_csrf_cookie(response):
    token = secrets.token_urlsafe(32)
    response.set_cookie(
        CSRF_COOKIE,
        token,
        httponly=False,
        secure=_secure_cookies(),
        samesite="Lax",
        max_age=12 * 60 * 60,
        path="/",
    )
    return response


def require_csrf(request_obj=request) -> None:
    require_same_origin(request_obj)
    expected = request_obj.cookies.get(CSRF_COOKIE)
    supplied = request_obj.headers.get("X-CSRF-Token") or request_obj.form.get("csrf_token")
    if not expected or not supplied or not secrets.compare_digest(expected, supplied):
        raise PermissionError("CSRF validation failed.")


def set_session_cookie(response, session_id: str):
    response.set_cookie(
        SESSION_COOKIE,
        session_id,
        httponly=True,
        secure=_secure_cookies(),
        samesite="Lax",
        max_age=12 * 60 * 60,
        path="/",
    )
    return issue_csrf_cookie(response)


def clear_session_cookie(response):
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return response


def _secure_cookies() -> bool:
    import os
    return os.getenv("WEB_SECURE_COOKIES", "false").strip().lower() == "true"
PY

cat > app/web/application.py <<'PY'
from __future__ import annotations

import os
from typing import Callable, Protocol

from flask import Flask, jsonify, redirect, render_template, request, url_for, g

from app.assistant.message import AssistantMessage
from app.assistant.response import AssistantResponse
from app.auth.errors import AuthenticationError, BusinessSelectionRequired
from app.auth.service import AuthenticationService
from app.auth.signup import SQLiteSignupTransaction, SignupConflict
from app.identity.models import UserRole
from app.models.business import Business
from app.models.voice import SUPPORTED_VOICES
from app.persistence.business_repository import SQLiteBusinessRepository
from app.persistence.credential_repository import SQLiteCredentialRepository
from app.persistence.database import SQLiteDatabase
from app.persistence.membership_repository import SQLiteMembershipRepository
from app.persistence.session import SQLiteSessionRepository
from app.persistence.user_repository import SQLiteUserRepository
from app.auth.rate_limit import SQLiteAuthenticationRateLimiter
from app.web.access import BusinessAccessDenied, BusinessAccessService
from app.web.auth import clear_session_cookie, install_auth_hooks, issue_csrf_cookie, login_required, require_csrf, set_session_cookie
from app.web.security import WebSecurityError


class OrchestratorLike(Protocol):
    def handle(self, message: AssistantMessage, confirmed: bool = False): ...


RuntimeBuilder = Callable[[Business], OrchestratorLike]


def create_app(*, database: SQLiteDatabase | None = None, runtime_builder: RuntimeBuilder | None = None, testing: bool = False) -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.update(TESTING=testing, MAX_CONTENT_LENGTH=64 * 1024, JSON_SORT_KEYS=False)

    db = database or SQLiteDatabase(os.getenv("ASSISTANT_DB_PATH", "data/assistant.sqlite3"))
    db.initialize()

    users = SQLiteUserRepository(db)
    credentials = SQLiteCredentialRepository(db)
    memberships = SQLiteMembershipRepository(db)
    sessions = SQLiteSessionRepository(db)
    auth_service = AuthenticationService(
        users=users,
        credentials=credentials,
        memberships=memberships,
        sessions=sessions,
        rate_limiter=SQLiteAuthenticationRateLimiter(db),
    )
    businesses = SQLiteBusinessRepository(db)
    access = BusinessAccessService(db)
    builder = runtime_builder or _production_runtime_builder

    install_auth_hooks(app, auth_service)
    app.extensions["assistant_database"] = db
    app.extensions["assistant_businesses"] = businesses
    app.extensions["assistant_access"] = access

    @app.errorhandler(BusinessAccessDenied)
    def access_denied(exc):
        return jsonify({"error": str(exc)}), 402

    @app.errorhandler(WebSecurityError)
    def web_security_error(exc):
        return jsonify({"error": str(exc)}), 403

    @app.errorhandler(PermissionError)
    def permission_error(exc):
        return jsonify({"error": str(exc)}), 403

    @app.errorhandler(ValueError)
    def value_error(exc):
        if request.path.startswith("/api/"):
            return jsonify({"error": str(exc)}), 400
        return "Bad request", 400

    @app.get("/")
    def index():
        return redirect(url_for("dashboard_page" if g.principal else "login_page"))

    @app.get("/login")
    def login_page():
        return issue_csrf_cookie(app.make_response(render_template("login.html")))

    @app.get("/signup")
    def signup_page():
        return issue_csrf_cookie(app.make_response(render_template("signup.html", voices=sorted(SUPPORTED_VOICES))))

    @app.get("/dashboard")
    @login_required
    def dashboard_page():
        business = businesses.get(g.principal.business_id)
        if business is None:
            return jsonify({"error": "Business not found."}), 404
        return render_template("dashboard.html", business=business, principal=g.principal, access=access.resolve(business.business_id))

    @app.post("/api/auth/signup")
    def signup_api():
        require_csrf(request)
        data = _json_object()
        try:
            user, business, _, _ = SQLiteSignupTransaction(db).signup(
                display_name=_required(data, "display_name"), email=_required(data, "email"), password=_required(data, "password"),
                business_name=_required(data, "business_name"), assistant_name=_required(data, "assistant_name"),
                assistant_voice=_required(data, "assistant_voice").lower(),
            )
        except SignupConflict as exc:
            return jsonify({"error": str(exc)}), 409
        return jsonify({"user_id": user.user_id, "business_id": business.business_id, "message": "Account created. Sign in to continue."}), 201

    @app.post("/api/auth/login")
    def login_api():
        require_csrf(request)
        data = _json_object()
        try:
            principal = auth_service.login(_required(data, "email"), _required(data, "password"), source_key="web")
        except BusinessSelectionRequired as exc:
            return jsonify({"error": "Business selection is required.", "businesses": [{"business_id": x[0], "name": x[1], "role": x[2]} for x in exc.memberships]}), 409
        except AuthenticationError:
            return jsonify({"error": "Authentication failed."}), 401
        return set_session_cookie(jsonify({"message": "Signed in.", "business_id": principal.business_id}), principal.session_id)

    @app.post("/api/auth/logout")
    @login_required
    def logout_api():
        require_csrf(request)
        token = request.cookies.get(SESSION_COOKIE)
        if token:
            auth_service.logout(token)
        return clear_session_cookie(jsonify({"message": "Signed out."}))

    @app.get("/api/me")
    @login_required
    def me_api():
        business = businesses.get(g.principal.business_id)
        if business is None:
            return jsonify({"error": "Business not found."}), 404
        business_access = access.resolve(business.business_id)
        return jsonify({"user_id": g.principal.user_id, "business_id": business.business_id, "role": g.principal.role.value, "business": {"name": business.name, "owner_name": business.owner_name, "assistant_name": business.assistant_name, "assistant_voice": business.assistant_voice}, "commercial": {"status": business_access.status.value, "allowed": business_access.allowed, "reason": business_access.reason, "trial_ends_at": business_access.trial_ends_at.isoformat() if business_access.trial_ends_at else None}})

    @app.post("/api/business/config")
    @login_required
    def update_business_config():
        require_csrf(request)
        if g.principal.role != UserRole.OWNER:
            return jsonify({"error": "Only the business owner may change assistant configuration."}), 403
        current = businesses.get(g.principal.business_id)
        if current is None:
            return jsonify({"error": "Business not found."}), 404
        data = _json_object()
        assistant_name = _required(data, "assistant_name")
        assistant_voice = _required(data, "assistant_voice").lower()
        if assistant_voice not in SUPPORTED_VOICES:
            return jsonify({"error": "Unsupported assistant voice."}), 400
        updated = Business(current.business_id, current.name, current.owner_name, assistant_name, assistant_voice)
        businesses.save(updated)
        return jsonify({"assistant_name": updated.assistant_name, "assistant_voice": updated.assistant_voice})

    @app.post("/api/assistant/message")
    @login_required
    def assistant_message_api():
        require_csrf(request)
        business = businesses.get(g.principal.business_id)
        if business is None:
            return jsonify({"error": "Business not found."}), 404
        access.require_execution(business.business_id)
        data = _json_object()
        text = _required(data, "message")
        if len(text) > 8000:
            return jsonify({"error": "Message is too long."}), 400
        result = builder(business).handle(AssistantMessage(business.business_id, text))
        if not isinstance(result, AssistantResponse):
            return jsonify({"error": "Assistant returned an invalid response."}), 500
        return jsonify({"assistant_name": result.assistant_name, "message": result.message, "should_speak": result.should_speak})

    return app


def _production_runtime_builder(business: Business) -> OrchestratorLike:
    from app.cli.assistant_factory import build_orchestrator_for_business
    return build_orchestrator_for_business(business)


def _json_object() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValueError("Request body must be a JSON object.")
    return data


def _required(data: dict, field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string.")
    return value.strip()
PY

cat > app/web/__init__.py <<'PY'
from app.web.application import create_app

__all__ = ["create_app"]
PY

cat > app/web/templates/login.html <<'HTML'
<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Business Assistant — Sign in</title><link rel="stylesheet" href="{{ url_for('static', filename='app.css') }}"></head><body><main class="shell"><section class="card"><p class="eyebrow">BUSINESS ASSISTANT</p><h1>Sign in</h1><p class="muted">Access your business assistant.</p><form id="login"><label>Email<input name="email" type="email" autocomplete="email" required></label><label>Password<input name="password" type="password" autocomplete="current-password" required></label><button>Sign in</button><p id="error" class="error"></p></form><p class="muted">New business? <a href="{{ url_for('signup_page') }}">Create an account</a></p></section></main><script src="{{ url_for('static', filename='app.js') }}"></script><script>wireAuthForm('login','/api/auth/login');</script></body></html>
HTML

cat > app/web/templates/signup.html <<'HTML'
<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Business Assistant — Create account</title><link rel="stylesheet" href="{{ url_for('static', filename='app.css') }}"></head><body><main class="shell"><section class="card"><p class="eyebrow">BUSINESS ASSISTANT</p><h1>Create your business</h1><p class="muted">Choose the identity and voice your assistant will use. The platform has no fixed assistant identity.</p><form id="signup"><label>Your name<input name="display_name" autocomplete="name" required></label><label>Email<input name="email" type="email" autocomplete="email" required></label><label>Password<input name="password" type="password" autocomplete="new-password" minlength="12" required></label><label>Business name<input name="business_name" required></label><label>Assistant name<input name="assistant_name" required></label><label>Voice<select name="assistant_voice" required>{% for voice in voices %}<option value="{{ voice }}">{{ voice|capitalize }}</option>{% endfor %}</select></label><button>Create account</button><p id="error" class="error"></p></form><p class="muted">Already registered? <a href="{{ url_for('login_page') }}">Sign in</a></p></section></main><script src="{{ url_for('static', filename='app.js') }}"></script><script>wireSignupForm();</script></body></html>
HTML

cat > app/web/templates/dashboard.html <<'HTML'
<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{{ business.name }} — Assistant</title><link rel="stylesheet" href="{{ url_for('static', filename='app.css') }}"></head><body><main class="dashboard"><header><div><p class="eyebrow">{{ business.name }}</p><h1>{{ business.assistant_name }}</h1><p class="muted">Your configured business assistant</p></div><button id="logout" class="secondary">Sign out</button></header><section class="grid"><article class="card"><h2>Talk to your assistant</h2><div id="messages" class="messages"></div><form id="assistant-form"><input name="message" placeholder="Say what you need…" autocomplete="off" required><button>Send</button></form><p id="assistant-error" class="error"></p></article><article class="card"><h2>Assistant setup</h2><form id="config-form"><label>Assistant name<input name="assistant_name" value="{{ business.assistant_name }}" required></label><label>Voice<select name="assistant_voice"><option value="male" {% if business.assistant_voice=='male' %}selected{% endif %}>Male</option><option value="female" {% if business.assistant_voice=='female' %}selected{% endif %}>Female</option></select></label><button>Save setup</button></form><p id="config-message" class="muted"></p><hr><p><strong>Access:</strong> {{ access.status.value }}</p><p class="muted">{{ access.reason }}</p></article></section></main><script src="{{ url_for('static', filename='app.js') }}"></script><script>wireDashboard();</script></body></html>
HTML

cat > app/web/static/app.css <<'CSS'
:root{font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#0b0b0d;color:#f5f5f5}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at top,#17171c,#09090b 55%);min-height:100vh}.shell{min-height:100vh;display:grid;place-items:center;padding:24px}.card{background:#141419;border:1px solid #2b2b33;border-radius:20px;padding:28px;box-shadow:0 20px 60px #0006}.shell .card{width:min(480px,100%)}h1,h2{margin-top:0}label{display:block;margin:16px 0;font-weight:600}input,select{width:100%;margin-top:8px;padding:13px 14px;border-radius:12px;border:1px solid #383842;background:#0d0d11;color:#fff;font:inherit}button{width:100%;border:0;border-radius:12px;padding:13px 16px;background:#f2c94c;color:#111;font-weight:800;cursor:pointer}button.secondary{width:auto;background:#24242b;color:#fff}.muted{color:#a8a8b2}.eyebrow{font-size:.75rem;letter-spacing:.14em;color:#d9bd58;font-weight:800}a{color:#f2c94c}.error{color:#ff8c8c;min-height:1.2em}.dashboard{width:min(1180px,100%);margin:auto;padding:24px}.dashboard header{display:flex;justify-content:space-between;gap:20px;align-items:center;margin-bottom:24px}.grid{display:grid;grid-template-columns:2fr 1fr;gap:20px}.messages{min-height:420px;max-height:60vh;overflow:auto;border:1px solid #292930;border-radius:14px;padding:16px;margin-bottom:14px}.message{padding:10px 12px;border-radius:12px;margin:8px 0;white-space:pre-wrap}.message.user{background:#25252c;margin-left:12%}.message.assistant{background:#1a1a20;margin-right:12%}.grid form button{margin-top:8px}@media(max-width:800px){.grid{grid-template-columns:1fr}.dashboard header{align-items:flex-start}.dashboard header button{margin-top:4px}}
CSS

cat > app/web/static/app.js <<'JS'
function csrf(){return document.cookie.split('; ').find(x=>x.startsWith('assistant_csrf='))?.split('=')[1]||''}
async function api(url,options={}){const headers={'Content-Type':'application/json','X-CSRF-Token':csrf(),...(options.headers||{})};const r=await fetch(url,{credentials:'same-origin',...options,headers});const data=await r.json().catch(()=>({}));if(!r.ok)throw new Error(data.error||'Request failed.');return data}
function wireAuthForm(id,url){document.getElementById(id).addEventListener('submit',async e=>{e.preventDefault();const f=new FormData(e.target),error=document.getElementById('error');error.textContent='';try{await api(url,{method:'POST',body:JSON.stringify(Object.fromEntries(f))});location.href='/dashboard'}catch(x){error.textContent=x.message}})}
function wireSignupForm(){document.getElementById('signup').addEventListener('submit',async e=>{e.preventDefault();const f=new FormData(e.target),error=document.getElementById('error');error.textContent='';try{await api('/api/auth/signup',{method:'POST',body:JSON.stringify(Object.fromEntries(f))});location.href='/login'}catch(x){error.textContent=x.message}})}
function addMessage(who,text){const box=document.getElementById('messages');const div=document.createElement('div');div.className='message '+who;div.textContent=text;box.appendChild(div);box.scrollTop=box.scrollHeight}
function wireDashboard(){document.getElementById('logout').onclick=async()=>{try{await api('/api/auth/logout',{method:'POST'})}finally{location.href='/login'}};document.getElementById('assistant-form').onsubmit=async e=>{e.preventDefault();const f=new FormData(e.target),text=f.get('message'),err=document.getElementById('assistant-error');err.textContent='';addMessage('user',text);e.target.reset();try{const data=await api('/api/assistant/message',{method:'POST',body:JSON.stringify({message:text})});addMessage('assistant',data.message)}catch(x){err.textContent=x.message}};document.getElementById('config-form').onsubmit=async e=>{e.preventDefault();const f=new FormData(e.target),msg=document.getElementById('config-message');try{await api('/api/business/config',{method:'POST',body:JSON.stringify(Object.fromEntries(f))});msg.textContent='Saved.'}catch(x){msg.textContent=x.message}}}
JS

cat > run_web.py <<'PY'
from app.web import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
PY

cat > tests/test_web_application.py <<'PY'
from datetime import datetime, timedelta, timezone

from app.assistant.message import AssistantMessage
from app.assistant.response import AssistantResponse
from app.commercial.trial import BusinessTrial
from app.persistence.database import SQLiteDatabase
from app.persistence.trial_repository import SQLiteTrialRepository
from app.web.application import create_app


class FakeOrchestrator:
    def handle(self, message: AssistantMessage, confirmed: bool = False):
        return AssistantResponse(message.business_id, "Configured Test Assistant", f"Received: {message.content}")


def make_app(tmp_path):
    db = SQLiteDatabase(tmp_path / "assistant.sqlite3")
    app = create_app(database=db, runtime_builder=lambda business: FakeOrchestrator(), testing=True)
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


def test_owner_can_change_assistant_configuration(tmp_path):
    app, _ = make_app(tmp_path)
    client = app.test_client()
    signup(client)
    login(client)
    response = client.post("/api/business/config", json={"assistant_name": "Friday", "assistant_voice": "female"}, headers={"X-CSRF-Token": client.get_cookie("assistant_csrf").value})
    assert response.status_code == 200
    assert response.get_json()["assistant_name"] == "Friday"


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


def test_cross_origin_state_change_is_rejected(tmp_path):
    app, _ = make_app(tmp_path)
    client = app.test_client()
    token = csrf(client)
    response = client.post("/api/auth/login", json={"email": "owner@example.com", "password": "correct horse battery staple"}, headers={"X-CSRF-Token": token, "Origin": "https://attacker.example"})
    assert response.status_code == 403
PY

python -m compileall -q app run_web.py tests/test_web_application.py
pytest -q tests/test_web_application.py

git diff --check

echo "PHASE 2 WEB INSTALLER READY"
echo "Backup directory on target: $BACKUP"
