import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


class Config:
    APP_ENV = os.getenv("APP_ENV", "development")
    FLASK_DEBUG = os.getenv("FLASK_DEBUG", "0") == "1"
    APP_HOST = os.getenv("APP_HOST", "127.0.0.1")
    APP_PORT = int(os.getenv("APP_PORT", "5050"))
    TRUSTED_HOSTS = [
        host.strip()
        for host in os.getenv("TRUSTED_HOSTS", "").split(",")
        if host.strip()
    ] or None
    SECRET_KEY = os.getenv("SECRET_KEY", "development-only-change-me")
    AUTH_REQUIRED = os.getenv("AUTH_REQUIRED", "1") == "1"
    MOBILE_MIN_SUPPORTED_VERSION_CODE = int(
        os.getenv("MOBILE_MIN_SUPPORTED_VERSION_CODE", "1")
    )
    MOBILE_LATEST_VERSION_CODE = int(
        os.getenv("MOBILE_LATEST_VERSION_CODE", "1")
    )
    MOBILE_MAINTENANCE_MODE = (
        os.getenv("MOBILE_MAINTENANCE_MODE", "0") == "1"
    )
    MOBILE_MAINTENANCE_MESSAGE = os.getenv(
        "MOBILE_MAINTENANCE_MESSAGE",
        "Planlı bakım nedeniyle kısa süre içinde tekrar deneyin.",
    ).strip()
    MOBILE_UPDATE_MESSAGE = os.getenv(
        "MOBILE_UPDATE_MESSAGE",
        "Devam etmek için uygulamanın güncel sürümünü yükleyin.",
    ).strip()
    MOBILE_UPDATE_URL = os.getenv("MOBILE_UPDATE_URL", "").strip()
    PRIVACY_POLICY_URL = os.getenv(
        "PRIVACY_POLICY_URL",
        "",
    ).strip()
    VIDEO_CONSENT_VERSION = os.getenv(
        "VIDEO_CONSENT_VERSION",
        "video-processing-v1",
    ).strip()
    REQUIRE_VIDEO_CONSENT = (
        os.getenv("REQUIRE_VIDEO_CONSENT", "1") == "1"
    )

    MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "yedi_yirmi_dort")
    STRICT_DATA_HYGIENE = (
        os.getenv("STRICT_DATA_HYGIENE", "0") == "1"
    )

    UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", str(BASE_DIR / "instance" / "uploads"))
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH_MB", "200")) * 1024 * 1024
    MAX_JSON_CONTENT_LENGTH = int(
        os.getenv("MAX_JSON_CONTENT_LENGTH_KB", "1024")
    ) * 1024

    ALLOWED_VIDEO_EXTENSIONS = {"mp4", "mov", "m4v", "webm"}
    VIDEO_VALIDATE_CONTENT = (
        os.getenv("VIDEO_VALIDATE_CONTENT", "1") == "1"
    )
    FFPROBE_PATH = os.getenv("FFPROBE_PATH", "ffprobe").strip()
    VIDEO_DELETE_SOURCE_AFTER_PROCESSING = (
        os.getenv("VIDEO_DELETE_SOURCE_AFTER_PROCESSING", "1") == "1"
    )
    VIDEO_PROCESSING_INLINE = os.getenv("VIDEO_PROCESSING_INLINE", "0") == "1"
    VIDEO_PROCESSING_MODE = os.getenv("VIDEO_PROCESSING_MODE", "thread")
    VIDEO_JOB_MAX_ATTEMPTS = int(
        os.getenv("VIDEO_JOB_MAX_ATTEMPTS", "3")
    )
    VIDEO_JOB_LEASE_SECONDS = int(
        os.getenv("VIDEO_JOB_LEASE_SECONDS", "900")
    )
    VIDEO_JOB_HEARTBEAT_SECONDS = int(
        os.getenv("VIDEO_JOB_HEARTBEAT_SECONDS", "60")
    )
    VIDEO_JOB_RETRY_BASE_SECONDS = int(
        os.getenv("VIDEO_JOB_RETRY_BASE_SECONDS", "15")
    )
    VIDEO_JOB_RETRY_MAX_SECONDS = int(
        os.getenv("VIDEO_JOB_RETRY_MAX_SECONDS", "900")
    )
    VIDEO_JOB_RETENTION_SECONDS = int(
        os.getenv(
            "VIDEO_JOB_RETENTION_SECONDS",
            str(7 * 24 * 60 * 60),
        )
    )
    VIDEO_WORKER_POLL_SECONDS = float(
        os.getenv("VIDEO_WORKER_POLL_SECONDS", "2")
    )
    VIDEO_WORKER_HEARTBEAT_SECONDS = int(
        os.getenv("VIDEO_WORKER_HEARTBEAT_SECONDS", "10")
    )
    VIDEO_WORKER_WARMUP_MODEL = (
        os.getenv("VIDEO_WORKER_WARMUP_MODEL", "0") == "1"
    )
    VIDEO_UPLOAD_RATE_LIMIT_WINDOW_SECONDS = int(
        os.getenv("VIDEO_UPLOAD_RATE_LIMIT_WINDOW_SECONDS", "86400")
    )
    VIDEO_UPLOAD_MAX_REQUESTS = int(
        os.getenv("VIDEO_UPLOAD_MAX_REQUESTS", "3")
    )

    TRANSCRIPTION_PROVIDER = os.getenv("TRANSCRIPTION_PROVIDER", "faster_whisper")
    TRANSCRIPTION_LANGUAGE = os.getenv("TRANSCRIPTION_LANGUAGE", "tr") or None
    TRANSCRIPTION_STATIC_TEXT = os.getenv("TRANSCRIPTION_STATIC_TEXT", "")
    FASTER_WHISPER_MODEL_SIZE = os.getenv("FASTER_WHISPER_MODEL_SIZE", "tiny")
    FASTER_WHISPER_DEVICE = os.getenv("FASTER_WHISPER_DEVICE", "cpu")
    FASTER_WHISPER_COMPUTE_TYPE = os.getenv("FASTER_WHISPER_COMPUTE_TYPE", "int8")
    JOB_RECOMMENDATION_FALLBACK_ENABLED = (
        os.getenv("JOB_RECOMMENDATION_FALLBACK_ENABLED", "0") == "1"
    )

    SMS_PROVIDER = os.getenv("SMS_PROVIDER", "console")
    TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
    TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER", "")
    OTP_TTL_SECONDS = int(os.getenv("OTP_TTL_SECONDS", "300"))
    OTP_REQUEST_COOLDOWN_SECONDS = int(
        os.getenv("OTP_REQUEST_COOLDOWN_SECONDS", "60")
    )
    OTP_RATE_LIMIT_WINDOW_SECONDS = int(
        os.getenv("OTP_RATE_LIMIT_WINDOW_SECONDS", "900")
    )
    OTP_PHONE_MAX_REQUESTS = int(
        os.getenv("OTP_PHONE_MAX_REQUESTS", "5")
    )
    OTP_IP_MAX_REQUESTS = int(
        os.getenv("OTP_IP_MAX_REQUESTS", "20")
    )
    OTP_MAX_ATTEMPTS = int(os.getenv("OTP_MAX_ATTEMPTS", "5"))
    OTP_STATIC_CODE = os.getenv("OTP_STATIC_CODE", "")
    OTP_EXPOSE_CODE = os.getenv("OTP_EXPOSE_CODE", "0") == "1"
    WORKER_SESSION_TTL_SECONDS = int(
        os.getenv("WORKER_SESSION_TTL_SECONDS", str(30 * 24 * 60 * 60))
    )

    ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
    ADMIN_PASSWORD_HASH = os.getenv("ADMIN_PASSWORD_HASH", "")
    ADMIN_EMPLOYER_KEY = os.getenv("ADMIN_EMPLOYER_KEY", "default")
    ADMIN_SESSION_TTL_SECONDS = int(
        os.getenv("ADMIN_SESSION_TTL_SECONDS", str(8 * 60 * 60))
    )
    ADMIN_LOGIN_MAX_ATTEMPTS = int(
        os.getenv("ADMIN_LOGIN_MAX_ATTEMPTS", "5")
    )
    ADMIN_LOGIN_WINDOW_SECONDS = int(
        os.getenv("ADMIN_LOGIN_WINDOW_SECONDS", "900")
    )
    ADMIN_AUDIT_RETENTION_DAYS = int(
        os.getenv("ADMIN_AUDIT_RETENTION_DAYS", "365")
    )
    ACCOUNT_DELETION_AUDIT_RETENTION_DAYS = int(
        os.getenv(
            "ACCOUNT_DELETION_AUDIT_RETENTION_DAYS",
            "365",
        )
    )
    WORKER_INVITATION_TTL_DAYS = int(
        os.getenv("WORKER_INVITATION_TTL_DAYS", "30")
    )
    WORKER_QUESTION_RATE_LIMIT_WINDOW_SECONDS = int(
        os.getenv("WORKER_QUESTION_RATE_LIMIT_WINDOW_SECONDS", "3600")
    )
    WORKER_QUESTION_MAX_REQUESTS = int(
        os.getenv("WORKER_QUESTION_MAX_REQUESTS", "20")
    )
    PUSH_PROVIDER = os.getenv("PUSH_PROVIDER", "disabled")
    FCM_PROJECT_ID = os.getenv("FCM_PROJECT_ID", "").strip()
    PUSH_JOB_MAX_ATTEMPTS = int(
        os.getenv("PUSH_JOB_MAX_ATTEMPTS", "5")
    )
    PUSH_JOB_LEASE_SECONDS = int(
        os.getenv("PUSH_JOB_LEASE_SECONDS", "60")
    )
    PUSH_JOB_RETRY_BASE_SECONDS = int(
        os.getenv("PUSH_JOB_RETRY_BASE_SECONDS", "15")
    )
    PUSH_JOB_RETRY_MAX_SECONDS = int(
        os.getenv("PUSH_JOB_RETRY_MAX_SECONDS", "900")
    )
    PUSH_JOB_RETENTION_SECONDS = int(
        os.getenv(
            "PUSH_JOB_RETENTION_SECONDS",
            str(7 * 24 * 60 * 60),
        )
    )
    PUSH_WORKER_POLL_SECONDS = float(
        os.getenv("PUSH_WORKER_POLL_SECONDS", "2")
    )
    PUSH_WORKER_HEARTBEAT_SECONDS = int(
        os.getenv("PUSH_WORKER_HEARTBEAT_SECONDS", "10")
    )
    PUSH_WORKER_VALIDATE_CREDENTIALS = (
        os.getenv("PUSH_WORKER_VALIDATE_CREDENTIALS", "0") == "1"
    )
    PUSH_REGISTRATION_RETENTION_DAYS = int(
        os.getenv("PUSH_REGISTRATION_RETENTION_DAYS", "90")
    )
    PUSH_MAX_ACTIVE_REGISTRATIONS_PER_WORKER = int(
        os.getenv(
            "PUSH_MAX_ACTIVE_REGISTRATIONS_PER_WORKER",
            "5",
        )
    )
    PUSH_MAX_STORED_REGISTRATIONS_PER_WORKER = int(
        os.getenv(
            "PUSH_MAX_STORED_REGISTRATIONS_PER_WORKER",
            "20",
        )
    )
    REQUIRE_IDEMPOTENCY_KEY = (
        os.getenv("REQUIRE_IDEMPOTENCY_KEY", "1") == "1"
    )
    IDEMPOTENCY_RETENTION_SECONDS = int(
        os.getenv("IDEMPOTENCY_RETENTION_SECONDS", "86400")
    )
    IDEMPOTENCY_PROCESSING_TIMEOUT_SECONDS = int(
        os.getenv(
            "IDEMPOTENCY_PROCESSING_TIMEOUT_SECONDS", "120"
        )
    )
    IDEMPOTENCY_UPLOAD_PROCESSING_TIMEOUT_SECONDS = int(
        os.getenv(
            "IDEMPOTENCY_UPLOAD_PROCESSING_TIMEOUT_SECONDS", "900"
        )
    )
    TRUSTED_PROXY_COUNT = int(os.getenv("TRUSTED_PROXY_COUNT", "0"))

    SESSION_COOKIE_SECURE = APP_ENV == "production"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
