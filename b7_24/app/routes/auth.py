from flask import Blueprint, current_app, g, jsonify, request
from werkzeug.exceptions import BadRequest

from app.auth import (
    ADMIN_CSRF_COOKIE,
    ADMIN_SESSION_COOKIE,
    get_current_principal,
    require_auth,
)
from app.db import get_db
from app.serializers import serialize_user
from app.services.auth import (
    authenticate_admin,
    create_otp_challenge,
    revoke_access_session,
    rotate_csrf_token,
    validate_csrf_token,
    verify_otp_challenge,
)


auth_bp = Blueprint("auth", __name__)


@auth_bp.post("/api/auth/otp/request")
def request_otp():
    payload = _json_object()
    challenge, exposed_code = create_otp_challenge(
        get_db(),
        current_app.config,
        payload.get("phone"),
        request.remote_addr,
    )
    response = {
        "challengeId": str(challenge["_id"]),
        "phone": challenge["phone"],
        "expiresIn": current_app.config["OTP_TTL_SECONDS"],
        "resendAfterSeconds": current_app.config[
            "OTP_REQUEST_COOLDOWN_SECONDS"
        ],
    }
    if exposed_code:
        response["devCode"] = exposed_code
    return jsonify(response), 202


@auth_bp.post("/api/auth/otp/verify")
def verify_otp():
    payload = _json_object()
    user, session, token = verify_otp_challenge(
        get_db(),
        current_app.config,
        payload.get("challengeId", ""),
        payload.get("phone"),
        payload.get("code"),
    )
    return jsonify(
        {
            "accessToken": token,
            "tokenType": "Bearer",
            "expiresIn": current_app.config["WORKER_SESSION_TTL_SECONDS"],
            "user": serialize_user(user),
        }
    )


@auth_bp.post("/api/admin/auth/login")
def admin_login():
    payload = _json_object()
    session, token, csrf_token = authenticate_admin(
        get_db(),
        current_app.config,
        payload.get("username"),
        payload.get("password"),
        request.remote_addr,
    )
    response = jsonify(
        {
            "expiresIn": current_app.config["ADMIN_SESSION_TTL_SECONDS"],
            "admin": {
                "username": session.get("username"),
                "employerKey": session.get("employerKey"),
                "role": session.get("role"),
            },
        }
    )
    _set_admin_cookies(response, token, csrf_token)
    return response


@auth_bp.get("/api/auth/me")
@require_auth
def auth_me():
    principal = get_current_principal()
    response = jsonify(
        {
            "principal": {
                "role": principal.get("role"),
                "userId": (
                    str(principal["userId"])
                    if principal.get("userId")
                    else None
                ),
                "employerKey": principal.get("employerKey"),
                "username": principal.get("username"),
                "expiresAt": principal.get("expiresAt").isoformat(),
            }
        }
    )
    if (
        getattr(g, "auth_source", None) == "cookie"
        and principal.get("role") == "employer"
    ):
        csrf_token = request.cookies.get(ADMIN_CSRF_COOKIE)
        if not validate_csrf_token(principal, csrf_token):
            csrf_token = rotate_csrf_token(get_db(), principal)
        _set_csrf_cookie(response, csrf_token)
    return response


@auth_bp.post("/api/auth/logout")
@require_auth
def logout():
    token = getattr(g, "access_token", None)
    if token:
        revoke_access_session(get_db(), token)
    response = current_app.response_class(status=204)
    response.delete_cookie(ADMIN_SESSION_COOKIE, path="/")
    response.delete_cookie(ADMIN_CSRF_COOKIE, path="/")
    return response


def _set_admin_cookies(response, token: str, csrf_token: str) -> None:
    secure = current_app.config.get("SESSION_COOKIE_SECURE", False)
    max_age = current_app.config["ADMIN_SESSION_TTL_SECONDS"]
    response.set_cookie(
        ADMIN_SESSION_COOKIE,
        token,
        max_age=max_age,
        secure=secure,
        httponly=True,
        samesite="Strict",
        path="/",
    )
    _set_csrf_cookie(response, csrf_token)


def _set_csrf_cookie(response, csrf_token: str) -> None:
    response.set_cookie(
        ADMIN_CSRF_COOKIE,
        csrf_token,
        max_age=current_app.config["ADMIN_SESSION_TTL_SECONDS"],
        secure=current_app.config.get("SESSION_COOKIE_SECURE", False),
        httponly=False,
        samesite="Strict",
        path="/",
    )


def _json_object() -> dict:
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise BadRequest("Request body must be a JSON object")
    return payload
