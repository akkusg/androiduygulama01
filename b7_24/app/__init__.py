import re
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from flask import Flask, g, jsonify, request
from werkzeug.exceptions import HTTPException
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.middleware.proxy_fix import ProxyFix

from app.config import Config
from app.db import ensure_indexes, init_db
from app.routes import (
    admin_bp,
    auth_bp,
    dashboard_bp,
    devices_bp,
    health_bp,
    job_applications_bp,
    job_postings_bp,
    users_bp,
    videos_bp,
    worker_support_bp,
)
from app.services.audit import record_admin_audit_event

REQUEST_ID_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$"
)


def create_app(config_object: type[Config] = Config) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_object)
    _validate_runtime_config(app)
    trusted_proxy_count = app.config.get("TRUSTED_PROXY_COUNT", 0)
    if trusted_proxy_count:
        app.wsgi_app = ProxyFix(
            app.wsgi_app,
            x_for=trusted_proxy_count,
            x_proto=trusted_proxy_count,
        )

    init_db(app)

    app.register_blueprint(health_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(videos_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(devices_bp)
    app.register_blueprint(job_applications_bp)
    app.register_blueprint(job_postings_bp)
    app.register_blueprint(worker_support_bp)

    @app.before_request
    def prepare_request():
        supplied_request_id = request.headers.get(
            "X-Request-ID", ""
        ).strip()
        g.request_id = (
            supplied_request_id
            if REQUEST_ID_PATTERN.fullmatch(supplied_request_id)
            else uuid4().hex
        )
        if (
            request.is_json
            and request.content_length is not None
            and request.content_length
            > app.config.get("MAX_JSON_CONTENT_LENGTH", 1024 * 1024)
        ):
            raise RequestEntityTooLarge(
                "JSON request body is too large"
            )
        if request.path not in {"/api/live", "/api/mobile-config"}:
            ensure_indexes()

    @app.errorhandler(HTTPException)
    def handle_http_error(error: HTTPException):
        response = jsonify(
            {
                "error": error.name,
                "message": error.description,
                "requestId": getattr(g, "request_id", None),
            }
        )
        retry_after = getattr(error, "retry_after", None)
        if retry_after:
            response.headers["Retry-After"] = str(retry_after)
        return response, error.code

    @app.errorhandler(Exception)
    def handle_unexpected_error(error: Exception):
        app.logger.exception(
            "Unhandled error requestId=%s: %s",
            getattr(g, "request_id", None),
            error,
        )
        return (
            jsonify(
                {
                    "error": "Internal Server Error",
                    "message": "Unexpected server error",
                    "requestId": getattr(g, "request_id", None),
                }
            ),
            500,
        )

    @app.after_request
    def add_security_headers(response):
        try:
            record_admin_audit_event(response.status_code)
        except Exception:
            app.logger.exception(
                "Admin audit event could not be recorded requestId=%s",
                getattr(g, "request_id", None),
            )
        response.headers["X-Request-ID"] = getattr(
            g, "request_id", uuid4().hex
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self'; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "font-src 'self'; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "frame-ancestors 'none'; "
            "form-action 'self'"
        )
        if request.path.startswith(("/api/", "/admin")):
            response.headers["Cache-Control"] = "no-store"
        if app.config.get("APP_ENV") == "production":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        return response

    return app


def _validate_runtime_config(app: Flask) -> None:
    if app.config.get("APP_ENV") != "production":
        return

    errors = []
    secret_key = app.config.get("SECRET_KEY", "")
    if (
        len(secret_key) < 32
        or secret_key == "development-only-change-me"  # nosec B105
    ):
        errors.append("SECRET_KEY must be a unique value of at least 32 characters")
    if app.config.get("FLASK_DEBUG"):
        errors.append("FLASK_DEBUG must be disabled")
    if not app.config.get("AUTH_REQUIRED"):
        errors.append("AUTH_REQUIRED must be enabled")
    mongo_uri = app.config.get("MONGO_URI", "")
    errors.extend(_production_mongo_uri_errors(mongo_uri))
    if not app.config.get("STRICT_DATA_HYGIENE"):
        errors.append("STRICT_DATA_HYGIENE must be enabled")
    if not app.config.get("TRUSTED_HOSTS"):
        errors.append("TRUSTED_HOSTS must be configured")
    min_mobile_version = app.config.get(
        "MOBILE_MIN_SUPPORTED_VERSION_CODE", 0
    )
    latest_mobile_version = app.config.get(
        "MOBILE_LATEST_VERSION_CODE", 0
    )
    if min_mobile_version < 1:
        errors.append(
            "MOBILE_MIN_SUPPORTED_VERSION_CODE must be at least 1"
        )
    if latest_mobile_version < min_mobile_version:
        errors.append(
            "MOBILE_LATEST_VERSION_CODE must be greater than or equal "
            "to MOBILE_MIN_SUPPORTED_VERSION_CODE"
        )
    mobile_update_url = app.config.get("MOBILE_UPDATE_URL", "")
    try:
        parsed_mobile_update_url = urlsplit(mobile_update_url)
    except ValueError:
        parsed_mobile_update_url = None
    if (
        parsed_mobile_update_url is None
        or parsed_mobile_update_url.scheme != "https"
        or not parsed_mobile_update_url.hostname
    ):
        errors.append(
            "MOBILE_UPDATE_URL must be an absolute HTTPS URL"
        )
    if (
        app.config.get("MOBILE_MAINTENANCE_MODE")
        and not app.config.get("MOBILE_MAINTENANCE_MESSAGE", "").strip()
    ):
        errors.append(
            "MOBILE_MAINTENANCE_MESSAGE must be configured during maintenance"
        )
    if not app.config.get("MOBILE_UPDATE_MESSAGE", "").strip():
        errors.append("MOBILE_UPDATE_MESSAGE must be configured")
    privacy_policy_url = app.config.get("PRIVACY_POLICY_URL", "")
    try:
        parsed_privacy_policy_url = urlsplit(privacy_policy_url)
    except ValueError:
        parsed_privacy_policy_url = None
    if (
        parsed_privacy_policy_url is None
        or parsed_privacy_policy_url.scheme != "https"
        or not parsed_privacy_policy_url.hostname
        or parsed_privacy_policy_url.hostname.casefold()
        in {
            "example.com",
            "www.example.com",
            "example.net",
            "www.example.net",
            "example.org",
            "www.example.org",
        }
        or parsed_privacy_policy_url.hostname.casefold().endswith(
            (".example", ".invalid", ".localhost", ".test")
        )
    ):
        errors.append(
            "PRIVACY_POLICY_URL must be a non-placeholder absolute HTTPS URL"
        )
    consent_version = app.config.get(
        "VIDEO_CONSENT_VERSION", ""
    ).strip()
    if not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._-]{2,63}",
        consent_version,
    ):
        errors.append(
            "VIDEO_CONSENT_VERSION must contain 3 to 64 safe characters"
        )
    if not app.config.get("REQUIRE_VIDEO_CONSENT"):
        errors.append("REQUIRE_VIDEO_CONSENT must be enabled")
    if app.config.get("VIDEO_PROCESSING_MODE") != "worker":
        errors.append("VIDEO_PROCESSING_MODE must be worker")
    if not app.config.get("VIDEO_WORKER_WARMUP_MODEL"):
        errors.append(
            "VIDEO_WORKER_WARMUP_MODEL must be enabled"
        )
    if not app.config.get("VIDEO_VALIDATE_CONTENT"):
        errors.append("VIDEO_VALIDATE_CONTENT must be enabled")
    ffprobe_path = app.config.get("FFPROBE_PATH", "")
    if not ffprobe_path or not ffprobe_path.startswith("/"):
        errors.append(
            "FFPROBE_PATH must be an absolute executable path"
        )
    if not app.config.get("VIDEO_DELETE_SOURCE_AFTER_PROCESSING"):
        errors.append(
            "VIDEO_DELETE_SOURCE_AFTER_PROCESSING must be enabled"
        )
    if not 60 <= app.config.get(
        "VIDEO_UPLOAD_RATE_LIMIT_WINDOW_SECONDS", 0
    ) <= 7 * 24 * 60 * 60:
        errors.append(
            "VIDEO_UPLOAD_RATE_LIMIT_WINDOW_SECONDS must be between "
            "60 and 604800"
        )
    if not 1 <= app.config.get("VIDEO_UPLOAD_MAX_REQUESTS", 0) <= 100:
        errors.append("VIDEO_UPLOAD_MAX_REQUESTS must be between 1 and 100")
    if not 24 * 60 * 60 <= app.config.get(
        "VIDEO_JOB_RETENTION_SECONDS", 0
    ) <= 30 * 24 * 60 * 60:
        errors.append(
            "VIDEO_JOB_RETENTION_SECONDS must be between 86400 and 2592000"
        )
    if not 1024 <= app.config.get(
        "MAX_JSON_CONTENT_LENGTH", 0
    ) <= 10 * 1024 * 1024:
        errors.append(
            "MAX_JSON_CONTENT_LENGTH must be between 1 KB and 10 MB"
        )
    if not 60 <= app.config.get(
        "OTP_RATE_LIMIT_WINDOW_SECONDS", 0
    ) <= 24 * 60 * 60:
        errors.append(
            "OTP_RATE_LIMIT_WINDOW_SECONDS must be between 60 and 86400"
        )
    if not 1 <= app.config.get(
        "OTP_PHONE_MAX_REQUESTS", 0
    ) <= 100:
        errors.append(
            "OTP_PHONE_MAX_REQUESTS must be between 1 and 100"
        )
    if not 1 <= app.config.get("OTP_IP_MAX_REQUESTS", 0) <= 1000:
        errors.append(
            "OTP_IP_MAX_REQUESTS must be between 1 and 1000"
        )
    if not 60 <= app.config.get(
        "WORKER_QUESTION_RATE_LIMIT_WINDOW_SECONDS", 0
    ) <= 7 * 24 * 60 * 60:
        errors.append(
            "WORKER_QUESTION_RATE_LIMIT_WINDOW_SECONDS must be between "
            "60 and 604800"
        )
    if not 1 <= app.config.get(
        "WORKER_QUESTION_MAX_REQUESTS", 0
    ) <= 1000:
        errors.append(
            "WORKER_QUESTION_MAX_REQUESTS must be between 1 and 1000"
        )
    if app.config.get("PUSH_PROVIDER") != "fcm":
        errors.append("PUSH_PROVIDER must be fcm")
    if not app.config.get("FCM_PROJECT_ID"):
        errors.append("FCM_PROJECT_ID must be configured")
    if not app.config.get("PUSH_WORKER_VALIDATE_CREDENTIALS"):
        errors.append(
            "PUSH_WORKER_VALIDATE_CREDENTIALS must be enabled"
        )
    if not 1 <= app.config.get("PUSH_JOB_MAX_ATTEMPTS", 0) <= 20:
        errors.append("PUSH_JOB_MAX_ATTEMPTS must be between 1 and 20")
    if not 15 <= app.config.get("PUSH_JOB_LEASE_SECONDS", 0) <= 600:
        errors.append(
            "PUSH_JOB_LEASE_SECONDS must be between 15 and 600"
        )
    if not 1 <= app.config.get(
        "PUSH_JOB_RETRY_BASE_SECONDS", 0
    ) <= 300:
        errors.append(
            "PUSH_JOB_RETRY_BASE_SECONDS must be between 1 and 300"
        )
    if not 30 <= app.config.get(
        "PUSH_JOB_RETRY_MAX_SECONDS", 0
    ) <= 24 * 60 * 60:
        errors.append(
            "PUSH_JOB_RETRY_MAX_SECONDS must be between 30 and 86400"
        )
    if not 24 * 60 * 60 <= app.config.get(
        "PUSH_JOB_RETENTION_SECONDS", 0
    ) <= 30 * 24 * 60 * 60:
        errors.append(
            "PUSH_JOB_RETENTION_SECONDS must be between 86400 and 2592000"
        )
    if not 1 <= app.config.get(
        "PUSH_REGISTRATION_RETENTION_DAYS", 0
    ) <= 365:
        errors.append(
            "PUSH_REGISTRATION_RETENTION_DAYS must be between 1 and 365"
        )
    active_registration_limit = app.config.get(
        "PUSH_MAX_ACTIVE_REGISTRATIONS_PER_WORKER",
        0,
    )
    stored_registration_limit = app.config.get(
        "PUSH_MAX_STORED_REGISTRATIONS_PER_WORKER",
        0,
    )
    if not 1 <= active_registration_limit <= 20:
        errors.append(
            "PUSH_MAX_ACTIVE_REGISTRATIONS_PER_WORKER must be "
            "between 1 and 20"
        )
    if not (
        1
        <= stored_registration_limit
        <= 100
        and stored_registration_limit >= active_registration_limit
    ):
        errors.append(
            "PUSH_MAX_STORED_REGISTRATIONS_PER_WORKER must be "
            "between the active limit and 100"
        )
    if not app.config.get("REQUIRE_IDEMPOTENCY_KEY"):
        errors.append(
            "REQUIRE_IDEMPOTENCY_KEY must be enabled"
        )
    if not 3600 <= app.config.get(
        "IDEMPOTENCY_RETENTION_SECONDS", 0
    ) <= 7 * 24 * 60 * 60:
        errors.append(
            "IDEMPOTENCY_RETENTION_SECONDS must be between "
            "3600 and 604800"
        )
    if not 10 <= app.config.get(
        "IDEMPOTENCY_PROCESSING_TIMEOUT_SECONDS", 0
    ) <= 15 * 60:
        errors.append(
            "IDEMPOTENCY_PROCESSING_TIMEOUT_SECONDS must be between "
            "10 and 900"
        )
    if not 60 <= app.config.get(
        "IDEMPOTENCY_UPLOAD_PROCESSING_TIMEOUT_SECONDS", 0
    ) <= 30 * 60:
        errors.append(
            "IDEMPOTENCY_UPLOAD_PROCESSING_TIMEOUT_SECONDS must be "
            "between 60 and 1800"
        )
    if not 0 <= app.config.get("TRUSTED_PROXY_COUNT", 0) <= 10:
        errors.append("TRUSTED_PROXY_COUNT must be between 0 and 10")
    if app.config.get("SMS_PROVIDER") in {"console", "static"}:
        errors.append("a production SMS_PROVIDER must be configured")
    elif app.config.get("SMS_PROVIDER") != "twilio":
        errors.append("SMS_PROVIDER must be twilio")
    elif not all(
        app.config.get(key)
        for key in (
            "TWILIO_ACCOUNT_SID",
            "TWILIO_AUTH_TOKEN",
            "TWILIO_FROM_NUMBER",
        )
    ):
        errors.append("Twilio credentials must be configured")
    if app.config.get("OTP_STATIC_CODE"):
        errors.append("OTP_STATIC_CODE must be empty")
    if app.config.get("OTP_EXPOSE_CODE"):
        errors.append("OTP_EXPOSE_CODE must be disabled")
    if not app.config.get("ADMIN_USERNAME"):
        errors.append("ADMIN_USERNAME must be configured")
    admin_password_hash = app.config.get("ADMIN_PASSWORD_HASH", "")
    if not admin_password_hash:
        errors.append("ADMIN_PASSWORD_HASH must be configured")
    elif not _is_strong_scrypt_hash(admin_password_hash):
        errors.append(
            "ADMIN_PASSWORD_HASH must be a valid Werkzeug scrypt hash "
            "with production-strength parameters"
        )
    if app.config.get("ADMIN_PASSWORD"):
        errors.append("ADMIN_PASSWORD must not contain a plaintext production password")
    if not 30 <= app.config.get(
        "ADMIN_AUDIT_RETENTION_DAYS", 0
    ) <= 3650:
        errors.append(
            "ADMIN_AUDIT_RETENTION_DAYS must be between 30 and 3650"
        )
    if not 30 <= app.config.get(
        "ACCOUNT_DELETION_AUDIT_RETENTION_DAYS", 0
    ) <= 3650:
        errors.append(
            "ACCOUNT_DELETION_AUDIT_RETENTION_DAYS must be between "
            "30 and 3650"
        )
    if app.config.get("TRANSCRIPTION_PROVIDER") != "faster_whisper":
        errors.append(
            "TRANSCRIPTION_PROVIDER must be faster_whisper"
        )
    if app.config.get("JOB_RECOMMENDATION_FALLBACK_ENABLED"):
        errors.append(
            "JOB_RECOMMENDATION_FALLBACK_ENABLED must be disabled"
        )
    if errors:
        raise RuntimeError("Invalid production configuration: " + "; ".join(errors))


def _production_mongo_uri_errors(mongo_uri: str) -> list[str]:
    try:
        parsed = urlsplit(mongo_uri)
    except ValueError:
        parsed = None
    if (
        parsed is None
        or parsed.scheme not in {"mongodb", "mongodb+srv"}
        or not parsed.hostname
        or "localhost" in mongo_uri.casefold()
        or "127.0.0.1" in mongo_uri
    ):
        return ["MONGO_URI must be an explicit non-local MongoDB URI"]

    query = {
        key.casefold(): values[-1].casefold()
        for key, values in parse_qs(
            parsed.query, keep_blank_values=True
        ).items()
    }
    tls_value = query.get("tls", query.get("ssl"))
    tls_enabled = (
        tls_value not in {"false", "0", "no"}
        if parsed.scheme == "mongodb+srv"
        else tls_value in {"true", "1", "yes"}
    )
    errors = []
    if not tls_enabled:
        errors.append("MONGO_URI must enable TLS")
    if not parsed.username and not query.get("authmechanism"):
        errors.append(
            "MONGO_URI must include an authenticated identity"
        )
    return errors


def _is_strong_scrypt_hash(value: str) -> bool:
    match = re.fullmatch(
        r"scrypt:(\d+):(\d+):(\d+)\$[^$]{8,}\$[0-9a-fA-F]{64,}",
        value,
    )
    if match is None:
        return False
    work_factor, block_size, parallelism = (
        int(part) for part in match.groups()
    )
    return (
        work_factor >= 32768
        and work_factor & (work_factor - 1) == 0
        and block_size >= 8
        and parallelism >= 1
    )
