from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import UTC, datetime, timedelta

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from werkzeug.exceptions import (
    BadRequest,
    Conflict,
    ServiceUnavailable,
    TooManyRequests,
    Unauthorized,
)
from werkzeug.security import check_password_hash

from app.services.sms import send_otp_sms


PHONE_SEPARATORS = re.compile(r"[\s().-]+")
VALID_STORED_PHONE = re.compile(
    r"^(?:\+90\d{10}|\+(?!90)[1-9]\d{9,14})$"
)


def normalize_phone(raw_phone) -> str:
    if not isinstance(raw_phone, str):
        raise BadRequest("phone must be a string")

    phone = PHONE_SEPARATORS.sub("", raw_phone.strip())
    if phone.startswith("00"):
        phone = f"+{phone[2:]}"
    elif phone.startswith("0") and len(phone) == 11:
        phone = f"+90{phone[1:]}"
    elif phone.isdigit() and len(phone) == 10:
        phone = f"+90{phone}"
    elif phone.startswith("90") and len(phone) == 12:
        phone = f"+{phone}"
    elif phone.isdigit():
        phone = f"+{phone}"

    if not VALID_STORED_PHONE.fullmatch(phone):
        raise BadRequest("phone must be a valid international phone number")
    return phone


def create_otp_challenge(
    db, config, raw_phone, remote_address: str | None = None
) -> tuple[dict, str | None]:
    phone = normalize_phone(raw_phone)
    now = datetime.now(UTC)
    window_seconds = config.get(
        "OTP_RATE_LIMIT_WINDOW_SECONDS", 900
    )
    _consume_rate_limit(
        db,
        scope="otp-ip",
        value=remote_address or "unknown",
        maximum=config.get("OTP_IP_MAX_REQUESTS", 20),
        window_seconds=window_seconds,
        now=now,
    )
    _consume_rate_limit(
        db,
        scope="otp-phone",
        value=phone,
        maximum=config.get("OTP_PHONE_MAX_REQUESTS", 5),
        window_seconds=window_seconds,
        now=now,
    )
    cooldown = timedelta(seconds=config["OTP_REQUEST_COOLDOWN_SECONDS"])
    latest = db.otpChallenges.find_one(
        {"phone": phone}, sort=[("createdAt", -1)]
    )
    if latest and latest.get("createdAt") and latest["createdAt"] > now - cooldown:
        retry_after = max(
            1,
            int(
                (
                    latest["createdAt"] + cooldown - now
                ).total_seconds()
            ),
        )
        error = TooManyRequests("Please wait before requesting another code")
        error.retry_after = retry_after
        raise error

    db.otpChallenges.update_many(
        {"phone": phone, "consumedAt": None},
        {"$set": {"revokedAt": now}},
    )
    code = config.get("OTP_STATIC_CODE") or f"{secrets.randbelow(1_000_000):06d}"
    challenge_id = ObjectId()
    expires_at = now + timedelta(seconds=config["OTP_TTL_SECONDS"])
    challenge = {
        "_id": challenge_id,
        "phone": phone,
        "codeHash": _otp_hash(config["SECRET_KEY"], challenge_id, code),
        "attempts": 0,
        "maxAttempts": config["OTP_MAX_ATTEMPTS"],
        "consumedAt": None,
        "revokedAt": None,
        "createdAt": now,
        "expiresAt": expires_at,
    }
    db.otpChallenges.insert_one(challenge)

    try:
        send_otp_sms(config, phone, code)
    except Exception:
        db.otpChallenges.update_one(
            {"_id": challenge_id},
            {"$set": {"revokedAt": datetime.now(UTC)}},
        )
        raise

    exposed_code = code if config.get("OTP_EXPOSE_CODE") else None
    return challenge, exposed_code


def verify_otp_challenge(
    db, config, challenge_id: str, raw_phone, code
) -> tuple[dict, dict, str]:
    if not ObjectId.is_valid(challenge_id):
        raise BadRequest("Invalid OTP challenge id")
    phone = normalize_phone(raw_phone)
    if not isinstance(code, str) or not re.fullmatch(r"\d{6}", code):
        raise BadRequest("code must contain exactly 6 digits")

    challenge_object_id = ObjectId(challenge_id)
    challenge = db.otpChallenges.find_one(
        {"_id": challenge_object_id, "phone": phone}
    )
    if challenge is None:
        raise Unauthorized("Invalid verification challenge")

    now = datetime.now(UTC)
    if challenge.get("attempts", 0) >= challenge.get("maxAttempts", 5):
        raise TooManyRequests("Too many verification attempts")
    if challenge.get("consumedAt") or challenge.get("revokedAt"):
        raise Unauthorized("Verification challenge is no longer active")
    if challenge["expiresAt"] <= now:
        raise Unauthorized("Verification code has expired")

    challenge = db.otpChallenges.find_one_and_update(
        {
            "_id": challenge_object_id,
            "phone": phone,
            "consumedAt": None,
            "revokedAt": None,
            "expiresAt": {"$gt": now},
            "$expr": {"$lt": ["$attempts", "$maxAttempts"]},
        },
        {"$inc": {"attempts": 1}},
        return_document=ReturnDocument.AFTER,
    )
    if challenge is None:
        raise TooManyRequests("Too many verification attempts")

    expected_hash = _otp_hash(
        config["SECRET_KEY"], challenge_object_id, code
    )
    if not hmac.compare_digest(expected_hash, challenge["codeHash"]):
        remaining = challenge.get("maxAttempts", 5) - challenge.get(
            "attempts", 0
        )
        if remaining <= 0:
            db.otpChallenges.update_one(
                {"_id": challenge_object_id},
                {"$set": {"revokedAt": now}},
            )
        raise Unauthorized("Invalid verification code")

    consumed = db.otpChallenges.update_one(
        {"_id": challenge_object_id, "consumedAt": None, "revokedAt": None},
        {"$set": {"consumedAt": now}},
    )
    if consumed.modified_count != 1:
        raise Conflict("Verification challenge was already used")

    user = _get_or_create_user(db, phone, now)
    token, session = create_access_session(
        db,
        role="worker",
        ttl_seconds=config["WORKER_SESSION_TTL_SECONDS"],
        user_id=user["_id"],
        employer_key=user.get("employerKey") or "default",
    )
    return user, session, token


def authenticate_admin(
    db, config, username, password, remote_address: str | None
) -> tuple[dict, str, str]:
    if not isinstance(username, str) or not isinstance(password, str):
        raise BadRequest("username and password must be strings")
    username = username.strip()
    if not username or not password:
        raise BadRequest("username and password are required")

    configured_username = config.get("ADMIN_USERNAME", "")
    configured_password = config.get("ADMIN_PASSWORD", "")
    configured_hash = config.get("ADMIN_PASSWORD_HASH", "")
    if not configured_username or (not configured_password and not configured_hash):
        raise ServiceUnavailable("Admin login is not configured")

    now = datetime.now(UTC)
    attempt_key = _login_attempt_key(username, remote_address)
    recent_failures = db.adminLoginAttempts.count_documents(
        {
            "attemptKey": attempt_key,
            "success": False,
            "createdAt": {
                "$gte": now
                - timedelta(seconds=config["ADMIN_LOGIN_WINDOW_SECONDS"])
            },
        }
    )
    if recent_failures >= config["ADMIN_LOGIN_MAX_ATTEMPTS"]:
        raise TooManyRequests("Too many login attempts")

    username_valid = secrets.compare_digest(username, configured_username)
    if configured_hash:
        password_valid = check_password_hash(configured_hash, password)
    else:
        password_valid = secrets.compare_digest(password, configured_password)

    success = username_valid and password_valid
    db.adminLoginAttempts.insert_one(
        {
            "attemptKey": attempt_key,
            "username": username,
            "success": success,
            "createdAt": now,
            "expiresAt": now
            + timedelta(seconds=config["ADMIN_LOGIN_WINDOW_SECONDS"]),
        }
    )
    if not success:
        raise Unauthorized("Invalid username or password")

    csrf_token = secrets.token_urlsafe(32)
    token, session = create_access_session(
        db,
        role="employer",
        ttl_seconds=config["ADMIN_SESSION_TTL_SECONDS"],
        employer_key=config.get("ADMIN_EMPLOYER_KEY") or "default",
        username=configured_username,
        csrf_token=csrf_token,
    )
    return session, token, csrf_token


def create_access_session(
    db,
    *,
    role: str,
    ttl_seconds: int,
    user_id: ObjectId | None = None,
    employer_key: str | None = None,
    username: str | None = None,
    csrf_token: str | None = None,
) -> tuple[str, dict]:
    now = datetime.now(UTC)
    token = secrets.token_urlsafe(48)
    session = {
        "tokenHash": _token_hash(token),
        "role": role,
        "userId": user_id,
        "employerKey": employer_key,
        "username": username,
        "createdAt": now,
        "lastUsedAt": now,
        "expiresAt": now + timedelta(seconds=ttl_seconds),
        "revokedAt": None,
    }
    if csrf_token:
        session["csrfTokenHash"] = _token_hash(csrf_token)
    result = db.authSessions.insert_one(session)
    session["_id"] = result.inserted_id
    return token, session


def find_access_session(db, token: str | None) -> dict | None:
    if not token:
        return None
    now = datetime.now(UTC)
    session = db.authSessions.find_one(
        {
            "tokenHash": _token_hash(token),
            "revokedAt": None,
            "expiresAt": {"$gt": now},
        }
    )
    if session:
        db.authSessions.update_one(
            {"_id": session["_id"]}, {"$set": {"lastUsedAt": now}}
        )
    return session


def revoke_access_session(db, token: str) -> bool:
    result = db.authSessions.update_one(
        {"tokenHash": _token_hash(token), "revokedAt": None},
        {"$set": {"revokedAt": datetime.now(UTC)}},
    )
    return result.modified_count == 1


def validate_csrf_token(session: dict, csrf_token: str | None) -> bool:
    expected_hash = session.get("csrfTokenHash")
    if not expected_hash or not csrf_token:
        return False
    return hmac.compare_digest(
        expected_hash,
        _token_hash(csrf_token),
    )


def rotate_csrf_token(db, session: dict) -> str:
    csrf_token = secrets.token_urlsafe(32)
    csrf_hash = _token_hash(csrf_token)
    db.authSessions.update_one(
        {"_id": session["_id"], "revokedAt": None},
        {"$set": {"csrfTokenHash": csrf_hash}},
    )
    session["csrfTokenHash"] = csrf_hash
    return csrf_token


def _consume_rate_limit(
    db,
    *,
    scope: str,
    value: str,
    maximum: int,
    window_seconds: int,
    now: datetime,
) -> None:
    window_epoch = (
        int(now.timestamp()) // window_seconds
    ) * window_seconds
    window_start = datetime.fromtimestamp(window_epoch, UTC)
    window_end = window_start + timedelta(seconds=window_seconds)
    query = {
        "rateKey": hashlib.sha256(
            f"{scope}:{value}".encode("utf-8")
        ).hexdigest(),
        "windowStart": window_start,
    }
    update = {
        "$inc": {"count": 1},
        "$setOnInsert": {
            "scope": scope,
            "createdAt": now,
            "expiresAt": window_end
            + timedelta(seconds=window_seconds),
        },
    }
    try:
        bucket = db.otpRateLimits.find_one_and_update(
            query,
            update,
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
    except DuplicateKeyError:
        bucket = db.otpRateLimits.find_one_and_update(
            query,
            {"$inc": {"count": 1}},
            return_document=ReturnDocument.AFTER,
        )

    if bucket and bucket.get("count", 0) > maximum:
        error = TooManyRequests("Too many verification code requests")
        error.retry_after = max(
            1, int((window_end - now).total_seconds())
        )
        raise error


def _get_or_create_user(db, phone: str, now: datetime) -> dict:
    invitation = db.workerInvitations.find_one_and_update(
        {
            "phone": phone,
            "status": "pending",
            "expiresAt": {"$gt": now},
        },
        {
            "$set": {
                "status": "accepted",
                "acceptedAt": now,
                "updatedAt": now,
            }
        },
        sort=[("createdAt", -1)],
        return_document=ReturnDocument.AFTER,
    )
    user = db.users.find_one({"phone": phone})
    if user is not None:
        updates = {}
        if not user.get("phoneVerifiedAt"):
            updates["phoneVerifiedAt"] = now
        if invitation and _can_accept_employer_assignment(user):
            updates["employerKey"] = invitation["employerKey"]
        if updates:
            updates["updatedAt"] = now
            db.users.update_one(
                {"_id": user["_id"]},
                {"$set": updates},
            )
            user = db.users.find_one({"_id": user["_id"]})
        return user

    employer_key = (
        invitation["employerKey"] if invitation else "default"
    )
    user = {
        "name": "",
        "nameStatus": "pending_video",
        "profileReviewStatus": "pending_video",
        "phone": phone,
        "phoneVerifiedAt": now,
        "employerKey": employer_key,
        "profileStatus": "registered",
        "videoStatus": "not_uploaded",
        "latestVideoId": None,
        "createdAt": now,
        "updatedAt": now,
    }
    try:
        result = db.users.insert_one(user)
        user["_id"] = result.inserted_id
        return user
    except DuplicateKeyError:
        return db.users.find_one({"phone": phone})


def _can_accept_employer_assignment(user: dict) -> bool:
    return (
        (user.get("employerKey") or "default") == "default"
        and user.get("videoStatus", "not_uploaded") == "not_uploaded"
        and user.get("profileStatus", "registered") == "registered"
    )


def _otp_hash(secret_key: str, challenge_id: ObjectId, code: str) -> str:
    return hmac.new(
        secret_key.encode("utf-8"),
        f"{challenge_id}:{code}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _login_attempt_key(username: str, remote_address: str | None) -> str:
    value = f"{username.casefold()}:{remote_address or 'unknown'}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
