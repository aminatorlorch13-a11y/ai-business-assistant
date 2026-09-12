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
            g.principal = auth_service.validate_session(token)
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
