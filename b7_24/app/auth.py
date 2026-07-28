from __future__ import annotations

from functools import wraps

from bson import ObjectId
from flask import current_app, g, request
from werkzeug.exceptions import Forbidden, Unauthorized

from app.db import get_db
from app.services.auth import find_access_session, validate_csrf_token


ADMIN_SESSION_COOKIE = "admin_session"
ADMIN_CSRF_COOKIE = "admin_csrf"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def get_bearer_token() -> str | None:
    authorization = request.headers.get("Authorization", "")
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.casefold() != "bearer" or not token.strip():
        return None
    return token.strip()


def get_access_token() -> tuple[str | None, str | None]:
    bearer_token = get_bearer_token()
    if bearer_token:
        return bearer_token, "bearer"

    cookie_token = request.cookies.get(ADMIN_SESSION_COOKIE, "").strip()
    if cookie_token:
        return cookie_token, "cookie"
    return None, None


def get_current_principal() -> dict:
    if "auth_session" in g:
        return g.auth_session

    token, auth_source = get_access_token()
    session = find_access_session(get_db(), token)
    if session is None:
        raise Unauthorized("A valid access token is required")
    if (
        auth_source == "cookie"
        and request.method not in SAFE_METHODS
        and not validate_csrf_token(
            session,
            request.headers.get("X-CSRF-Token"),
        )
    ):
        raise Forbidden("CSRF validation failed")
    g.auth_session = session
    g.access_token = token
    g.auth_source = auth_source
    return session


def require_auth(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_app.config.get("AUTH_REQUIRED", True):
            get_current_principal()
        return view(*args, **kwargs)

    return wrapped


def require_worker(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_app.config.get("AUTH_REQUIRED", True):
            return view(*args, **kwargs)

        principal = get_current_principal()
        if principal.get("role") != "worker":
            raise Forbidden("Worker access is required")

        user_id = kwargs.get("user_id")
        principal_user_id = principal.get("userId")
        if (
            user_id
            and (
                not isinstance(principal_user_id, ObjectId)
                or str(principal_user_id) != user_id
            )
        ):
            raise Forbidden("You cannot access another worker's data")
        return view(*args, **kwargs)

    return wrapped


def require_employer(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_app.config.get("AUTH_REQUIRED", True):
            return view(*args, **kwargs)

        principal = get_current_principal()
        if principal.get("role") != "employer":
            raise Forbidden("Employer access is required")

        employer_key = kwargs.get("employer_key")
        if employer_key and principal.get("employerKey") != employer_key:
            raise Forbidden("You cannot access another employer's data")
        return view(*args, **kwargs)

    return wrapped
