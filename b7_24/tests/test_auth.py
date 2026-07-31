import hashlib
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path

import pytest
from bson import ObjectId
from werkzeug.exceptions import BadRequest
from werkzeug.security import generate_password_hash

from app import create_app
from app.db import get_db
from app.services.account_deletion import (
    cleanup_account_deletion_files,
)
from app.services.auth import normalize_phone
from app.services.data_hygiene import build_data_hygiene_report


class AuthTestConfig:
    TESTING = True
    AUTH_REQUIRED = True
    SECRET_KEY = "auth-test-secret-key"
    MONGO_URI = "mongodb://localhost:27017"
    MONGO_DB_NAME = "yedi_yirmi_dort_auth_test"
    STRICT_DATA_HYGIENE = True
    UPLOAD_FOLDER = "/tmp/yedi_yirmi_dort_auth_test_uploads"
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024
    MAX_JSON_CONTENT_LENGTH = 1024 * 1024
    ALLOWED_VIDEO_EXTENSIONS = {"mp4"}
    VIDEO_VALIDATE_CONTENT = False
    FFPROBE_PATH = "/usr/bin/ffprobe"
    VIDEO_DELETE_SOURCE_AFTER_PROCESSING = True
    VIDEO_PROCESSING_INLINE = True
    VIDEO_WORKER_WARMUP_MODEL = True
    VIDEO_JOB_RETENTION_SECONDS = 604800
    VIDEO_UPLOAD_RATE_LIMIT_WINDOW_SECONDS = 86400
    VIDEO_UPLOAD_MAX_REQUESTS = 3
    REQUIRE_VIDEO_CONSENT = False
    VIDEO_CONSENT_VERSION = "video-processing-v1"
    PRIVACY_POLICY_URL = "https://example.com/privacy"
    TRANSCRIPTION_PROVIDER = "static"
    TRANSCRIPTION_STATIC_TEXT = "Adım Test Kullanıcı."
    TRANSCRIPTION_LANGUAGE = "tr"
    JOB_RECOMMENDATION_FALLBACK_ENABLED = True
    FASTER_WHISPER_MODEL_SIZE = "tiny"
    FASTER_WHISPER_DEVICE = "cpu"
    FASTER_WHISPER_COMPUTE_TYPE = "int8"
    SMS_PROVIDER = "static"
    OTP_TTL_SECONDS = 300
    OTP_REQUEST_COOLDOWN_SECONDS = 1
    OTP_RATE_LIMIT_WINDOW_SECONDS = 900
    OTP_PHONE_MAX_REQUESTS = 5
    OTP_IP_MAX_REQUESTS = 20
    OTP_MAX_ATTEMPTS = 3
    OTP_STATIC_CODE = "123456"
    OTP_EXPOSE_CODE = True
    WORKER_SESSION_TTL_SECONDS = 3600
    WORKER_QUESTION_RATE_LIMIT_WINDOW_SECONDS = 3600
    WORKER_QUESTION_MAX_REQUESTS = 20
    ADMIN_USERNAME = "admin"
    ADMIN_PASSWORD = "correct-password"
    ADMIN_PASSWORD_HASH = ""
    ADMIN_EMPLOYER_KEY = "default"
    ADMIN_SESSION_TTL_SECONDS = 3600
    ADMIN_LOGIN_MAX_ATTEMPTS = 5
    ADMIN_LOGIN_WINDOW_SECONDS = 900
    ADMIN_AUDIT_RETENTION_DAYS = 365
    ACCOUNT_DELETION_AUDIT_RETENTION_DAYS = 365
    REQUIRE_IDEMPOTENCY_KEY = False
    IDEMPOTENCY_RETENTION_SECONDS = 86400
    IDEMPOTENCY_PROCESSING_TIMEOUT_SECONDS = 120
    IDEMPOTENCY_UPLOAD_PROCESSING_TIMEOUT_SECONDS = 900
    TRUSTED_PROXY_COUNT = 0
    TRUSTED_HOSTS = None
    MOBILE_MIN_SUPPORTED_VERSION_CODE = 1
    MOBILE_LATEST_VERSION_CODE = 1
    MOBILE_MAINTENANCE_MODE = False
    MOBILE_MAINTENANCE_MESSAGE = "Planlı bakım."
    MOBILE_UPDATE_MESSAGE = "Uygulamayı güncelleyin."
    MOBILE_UPDATE_URL = (
        "https://play.google.com/store/apps/details?id=com.example.m7_24"
    )
    PUSH_PROVIDER = "static"
    FCM_PROJECT_ID = ""
    PUSH_JOB_MAX_ATTEMPTS = 3
    PUSH_JOB_LEASE_SECONDS = 60
    PUSH_JOB_RETRY_BASE_SECONDS = 1
    PUSH_JOB_RETRY_MAX_SECONDS = 30
    PUSH_JOB_RETENTION_SECONDS = 86400
    PUSH_WORKER_POLL_SECONDS = 0.01
    PUSH_WORKER_HEARTBEAT_SECONDS = 1
    PUSH_WORKER_VALIDATE_CREDENTIALS = True
    PUSH_REGISTRATION_RETENTION_DAYS = 90
    PUSH_MAX_ACTIVE_REGISTRATIONS_PER_WORKER = 5
    PUSH_MAX_STORED_REGISTRATIONS_PER_WORKER = 20


COLLECTIONS = [
    "users",
    "workerConsents",
    "videos",
    "videoTranscripts",
    "videoProcessingJobs",
    "videoWorkerHeartbeats",
    "candidateProfiles",
    "jobRecommendations",
    "jobPostings",
    "jobApplications",
    "jobHiringSlots",
    "workerSupportConfigs",
    "workerSupportAssignments",
    "workerInvitations",
    "workerQuestions",
    "workerAssessmentResults",
    "workerTrainingProgress",
    "workerShuttleRequests",
    "otpChallenges",
    "otpRateLimits",
    "actionRateLimits",
    "authSessions",
    "adminLoginAttempts",
    "adminAuditEvents",
    "idempotencyRecords",
    "accountDeletionRecords",
    "workerPushRegistrations",
    "pushNotificationJobs",
    "pushWorkerHeartbeats",
]


@pytest.fixture()
def auth_app():
    app = create_app(AuthTestConfig)
    with app.app_context():
        _clean_database(get_db())
    yield app
    with app.app_context():
        _clean_database(get_db())
    upload_dir = Path(AuthTestConfig.UPLOAD_FOLDER)
    if upload_dir.exists():
        for path in upload_dir.rglob("*"):
            if path.is_file():
                path.unlink()


@pytest.fixture()
def auth_client(auth_app):
    return auth_app.test_client()


def test_worker_otp_auth_scopes_access_and_supports_logout(auth_client):
    first = _authenticate_worker(auth_client, "0555 111 22 33")
    second = _authenticate_worker(auth_client, "+905552223344")

    assert first["challenge"]["phone"] == "+905551112233"
    assert first["challenge"]["devCode"] == "123456"
    assert (
        first["challenge"]["resendAfterSeconds"]
        == AuthTestConfig.OTP_REQUEST_COOLDOWN_SECONDS
    )
    assert first["auth"]["user"]["phoneVerifiedAt"] is not None

    own_dashboard = auth_client.get(
        f"/api/users/{first['userId']}/dashboard",
        headers=_bearer(first["token"]),
    )
    missing_token = auth_client.get(
        f"/api/users/{first['userId']}/dashboard"
    )
    other_worker = auth_client.get(
        f"/api/users/{second['userId']}/dashboard",
        headers=_bearer(first["token"]),
    )

    assert own_dashboard.status_code == 200
    assert missing_token.status_code == 401
    assert other_worker.status_code == 403

    logout = auth_client.post(
        "/api/auth/logout", headers=_bearer(first["token"])
    )
    after_logout = auth_client.get(
        f"/api/users/{first['userId']}/dashboard",
        headers=_bearer(first["token"]),
    )
    assert logout.status_code == 204
    assert after_logout.status_code == 401


@pytest.mark.parametrize(
    "raw_phone",
    [
        "+90 555 111 22 33",
        "0090 555 111 22 33",
        "90 555 111 22 33",
        "0555 111 22 33",
        "555 111 22 33",
    ],
)
def test_turkish_phone_formats_normalize_to_same_e164_number(raw_phone):
    assert normalize_phone(raw_phone) == "+905551112233"


@pytest.mark.parametrize(
    "raw_phone",
    [
        "+095551112233",
        "+90555923017",
        "123",
        "not-a-phone",
        "",
    ],
)
def test_invalid_phone_formats_are_rejected(raw_phone):
    with pytest.raises(BadRequest):
        normalize_phone(raw_phone)


def test_worker_account_deletion_erases_personal_data_and_revokes_session(
    auth_app,
    auth_client,
):
    authenticated = _authenticate_worker(
        auth_client,
        "+905551119988",
    )
    user_id = ObjectId(authenticated["userId"])
    now = datetime.now(UTC)
    video_id = ObjectId()
    upload_dir = Path(AuthTestConfig.UPLOAD_FOLDER) / str(user_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    source_path = upload_dir / "account-delete.mp4"
    source_path.write_bytes(b"private video")

    with auth_app.app_context():
        db = get_db()
        db.videos.insert_one(
            {
                "_id": video_id,
                "userId": user_id,
                "storedPath": str(source_path),
                "status": "processing",
                "createdAt": now,
            }
        )
        db.workerConsents.insert_one(
            {
                "userId": user_id,
                "type": "video_processing",
                "version": "video-processing-v1",
                "status": "accepted",
                "acceptedAt": now,
                "revokedAt": None,
                "createdAt": now,
                "updatedAt": now,
            }
        )
        db.videoTranscripts.insert_one(
            {
                "videoId": video_id,
                "userId": user_id,
                "text": "private transcript",
                "createdAt": now,
            }
        )
        db.candidateProfiles.insert_one(
            {
                "userId": user_id,
                "name": "Private Worker",
                "summary": "private summary",
            }
        )
        db.workerQuestions.insert_one(
            {
                "userId": user_id,
                "employerKey": "default",
                "question": "private question",
                "createdAt": now,
            }
        )
        posting_id = ObjectId()
        application_id = db.jobApplications.insert_one(
            {
                "userId": user_id,
                "jobRecommendationId": ObjectId(),
                "jobPostingId": posting_id,
                "employerKey": "default",
                "status": "offered",
                "hiringSlot": 1,
                "coverNote": "private cover note",
                "candidate": {
                    "name": "Private Worker",
                    "phone": "+905551119988",
                    "skills": ["private skill"],
                    "summary": "private summary",
                },
                "statusHistory": [
                    {
                        "status": "offered",
                        "note": "private note",
                        "changedAt": now,
                    }
                ],
                "interview": {
                    "scheduledAt": now,
                    "type": "onsite",
                    "location": "ACME",
                    "response": {
                        "status": "declined",
                        "note": "private interview response",
                        "respondedAt": now,
                    },
                    "updatedAt": now,
                },
                "offer": {
                    "startDate": now,
                    "expiresAt": now,
                    "note": "employer offer note",
                    "response": {
                        "status": "declined",
                        "note": "private offer response",
                        "respondedAt": now,
                    },
                    "updatedAt": now,
                },
                "createdAt": now,
                "updatedAt": now,
            }
        ).inserted_id
        db.jobHiringSlots.insert_one(
            {
                "jobPostingId": posting_id,
                "applicationId": application_id,
                "slot": 1,
                "createdAt": now,
                "updatedAt": now,
            }
        )
        db.actionRateLimits.insert_one(
            {
                "rateKey": hashlib.sha256(
                    f"video-upload:{user_id}".encode()
                ).hexdigest(),
                "windowStart": now,
                "scope": "video-upload",
                "count": 1,
                "expiresAt": now,
            }
        )
        db.idempotencyRecords.insert_one(
            {
                "scope": f"{user_id}:POST:test.action",
                "idempotencyKey": "account-delete-test-0001",
                "requestHash": "hash",
                "status": "completed",
                "expiresAt": now,
            }
        )

    deleted = auth_client.delete(
        f"/api/users/{user_id}",
        headers=_bearer(authenticated["token"]),
    )
    after_delete = auth_client.get(
        f"/api/users/{user_id}/dashboard",
        headers=_bearer(authenticated["token"]),
    )

    assert deleted.status_code == 204
    assert after_delete.status_code == 401
    assert not source_path.exists()
    with auth_app.app_context():
        db = get_db()
        assert db.users.count_documents({"_id": user_id}) == 0
        for collection_name in (
            "workerConsents",
            "videos",
            "videoTranscripts",
            "candidateProfiles",
            "workerQuestions",
        ):
            assert db[collection_name].count_documents(
                {"userId": user_id}
            ) == 0
        assert db.authSessions.count_documents(
            {"userId": user_id}
        ) == 0
        assert db.otpChallenges.count_documents(
            {"phone": "+905551119988"}
        ) == 0
        assert db.actionRateLimits.count_documents(
            {"scope": "video-upload"}
        ) == 0
        assert db.idempotencyRecords.count_documents(
            {"scope": {"$regex": f"^{user_id}:"}}
        ) == 0
        application = db.jobApplications.find_one(
            {"_id": application_id}
        )
        assert application["candidate"] == {
            "name": "Silinen kullanıcı",
            "phone": None,
            "profileStatus": "deleted",
            "skills": [],
            "summary": None,
        }
        assert application["coverNote"] == ""
        assert len(application["statusHistory"]) == 1
        assert (
            application["statusHistory"][0]["status"]
            == "offered"
        )
        assert "note" not in application["statusHistory"][0]
        assert "response" not in application["interview"]
        assert "response" not in application["offer"]
        assert "hiringSlot" not in application
        assert db.jobHiringSlots.count_documents(
            {"applicationId": application_id}
        ) == 0
        deletion = db.accountDeletionRecords.find_one(
            {"_id": user_id}
        )
        assert deletion["status"] == "completed"
        assert "phone" not in deletion
        assert (
            deletion["purgeAt"] - deletion["completedAt"]
        ).days == AuthTestConfig.ACCOUNT_DELETION_AUDIT_RETENTION_DAYS


def test_account_deletion_file_cleanup_retries_and_degrades_health(
    auth_app,
    auth_client,
    monkeypatch,
):
    authenticated = _authenticate_worker(
        auth_client,
        "+905551119977",
    )
    user_id = ObjectId(authenticated["userId"])
    upload_dir = Path(AuthTestConfig.UPLOAD_FOLDER) / str(user_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    source_path = upload_dir / "retry-delete.mp4"
    source_path.write_bytes(b"private video")
    with auth_app.app_context():
        get_db().videos.insert_one(
            {
                "_id": ObjectId(),
                "userId": user_id,
                "storedPath": str(source_path),
                "status": "processing",
                "createdAt": datetime.now(UTC),
            }
        )

    with monkeypatch.context() as patch:
        patch.setattr(
            Path,
            "unlink",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                PermissionError("storage unavailable")
            ),
        )
        deleted = auth_client.delete(
            f"/api/users/{user_id}",
            headers=_bearer(authenticated["token"]),
        )

    degraded = auth_client.get("/api/health")
    assert deleted.status_code == 204
    assert degraded.status_code == 503
    assert degraded.get_json()["accountDeletion"] == {
        "pendingFileCleanup": 1,
        "failedFileCleanup": 0,
    }
    assert source_path.exists()

    with auth_app.app_context():
        assert cleanup_account_deletion_files(
            get_db(),
            AuthTestConfig.UPLOAD_FOLDER,
        ) == 1
    recovered = auth_client.get("/api/health")

    assert not source_path.exists()
    assert recovered.status_code == 200
    assert recovered.get_json()["accountDeletion"] == {
        "pendingFileCleanup": 0,
        "failedFileCleanup": 0,
    }


def test_worker_otp_rejects_invalid_code_and_direct_registration(auth_client):
    challenge = auth_client.post(
        "/api/auth/otp/request", json={"phone": "+905553334455"}
    ).get_json()
    invalid = auth_client.post(
        "/api/auth/otp/verify",
        json={
            "challengeId": challenge["challengeId"],
            "phone": challenge["phone"],
            "code": "000000",
        },
    )
    valid = auth_client.post(
        "/api/auth/otp/verify",
        json={
            "challengeId": challenge["challengeId"],
            "phone": challenge["phone"],
            "code": "123456",
        },
    )
    direct_registration = auth_client.post(
        "/api/users", json={"phone": "+905559999999"}
    )

    assert invalid.status_code == 401
    assert valid.status_code == 200
    assert direct_registration.status_code == 401


def test_worker_otp_enforces_attempt_limit_atomically(auth_app, auth_client):
    challenge = auth_client.post(
        "/api/auth/otp/request", json={"phone": "+905553334466"}
    ).get_json()

    invalid_attempts = [
        auth_client.post(
            "/api/auth/otp/verify",
            json={
                "challengeId": challenge["challengeId"],
                "phone": challenge["phone"],
                "code": "000000",
            },
        )
        for _ in range(AuthTestConfig.OTP_MAX_ATTEMPTS)
    ]
    after_limit = auth_client.post(
        "/api/auth/otp/verify",
        json={
            "challengeId": challenge["challengeId"],
            "phone": challenge["phone"],
            "code": "123456",
        },
    )

    assert all(
        response.status_code == 401 for response in invalid_attempts
    )
    assert after_limit.status_code == 429
    with auth_app.app_context():
        stored = get_db().otpChallenges.find_one(
            {"_id": ObjectId(challenge["challengeId"])}
        )
        assert stored["attempts"] == AuthTestConfig.OTP_MAX_ATTEMPTS


def test_otp_requests_are_rate_limited_by_phone(
    auth_app, auth_client
):
    auth_app.config.update(
        OTP_REQUEST_COOLDOWN_SECONDS=0,
        OTP_RATE_LIMIT_WINDOW_SECONDS=60,
        OTP_PHONE_MAX_REQUESTS=2,
        OTP_IP_MAX_REQUESTS=10,
    )

    responses = [
        auth_client.post(
            "/api/auth/otp/request",
            json={"phone": "+905550001122"},
        )
        for _ in range(3)
    ]

    assert [response.status_code for response in responses] == [
        202,
        202,
        429,
    ]
    assert int(responses[-1].headers["Retry-After"]) > 0


def test_otp_challenge_reports_server_resend_cooldown(
    auth_app, auth_client
):
    auth_app.config["OTP_REQUEST_COOLDOWN_SECONDS"] = 7

    first = auth_client.post(
        "/api/auth/otp/request",
        json={"phone": "+905550001133"},
    )
    early_resend = auth_client.post(
        "/api/auth/otp/request",
        json={"phone": "+905550001133"},
    )

    assert first.status_code == 202
    assert first.get_json()["resendAfterSeconds"] == 7
    assert early_resend.status_code == 429
    assert 1 <= int(early_resend.headers["Retry-After"]) <= 7


def test_otp_requests_are_rate_limited_by_client_ip(
    auth_app, auth_client
):
    auth_app.config.update(
        OTP_REQUEST_COOLDOWN_SECONDS=0,
        OTP_RATE_LIMIT_WINDOW_SECONDS=60,
        OTP_PHONE_MAX_REQUESTS=10,
        OTP_IP_MAX_REQUESTS=2,
    )

    responses = [
        auth_client.post(
            "/api/auth/otp/request",
            json={"phone": f"+9055500022{index:02d}"},
        )
        for index in range(3)
    ]

    assert [response.status_code for response in responses] == [
        202,
        202,
        429,
    ]


def test_employer_auth_protects_admin_resources_and_tenant_scope(
    auth_app, auth_client
):
    worker = _authenticate_worker(auth_client, "+905554445566")
    unauthenticated = auth_client.get(
        "/api/employers/default/worker-config"
    )
    worker_forbidden = auth_client.get(
        "/api/employers/default/worker-config",
        headers=_bearer(worker["token"]),
    )
    wrong_password = auth_client.post(
        "/api/admin/auth/login",
        json={"username": "admin", "password": "wrong-password"},
    )
    login = auth_client.post(
        "/api/admin/auth/login",
        json={"username": "admin", "password": "correct-password"},
    )

    assert unauthenticated.status_code == 401
    assert worker_forbidden.status_code == 403
    assert wrong_password.status_code == 401
    assert login.status_code == 200

    assert "accessToken" not in login.get_json()
    set_cookie_headers = login.headers.getlist("Set-Cookie")
    assert any(
        "admin_session=" in header
        and "HttpOnly" in header
        and "SameSite=Strict" in header
        for header in set_cookie_headers
    )
    assert any(
        "admin_csrf=" in header and "SameSite=Strict" in header
        for header in set_cookie_headers
    )
    csrf_token = auth_client.get_cookie("admin_csrf").value
    own_config = auth_client.get(
        "/api/employers/default/worker-config",
    )
    other_tenant = auth_client.get(
        "/api/employers/acme/worker-config",
    )
    assert own_config.status_code == 200
    assert own_config.get_json()["workerConfig"]["employerKey"] == "default"
    assert other_tenant.status_code == 403

    missing_csrf = auth_client.post(
        "/api/employers/default/worker-invitations",
        json={"phone": "+905550004499"},
    )
    invitation = auth_client.post(
        "/api/employers/default/worker-invitations",
        headers={"X-CSRF-Token": csrf_token},
        json={"phone": "+905550004499"},
    )
    audit_events = auth_client.get(
        "/api/employers/default/audit-events",
    )
    other_tenant_audit = auth_client.get(
        "/api/employers/acme/audit-events",
    )
    with auth_app.app_context():
        now = datetime.now(UTC)
        db = get_db()
        db.videoProcessingJobs.insert_one(
            {
                "videoId": ObjectId(),
                "userId": ObjectId(worker["userId"]),
                "status": "failed",
                "createdAt": now,
                "updatedAt": now,
                "failedAt": now,
                "purgeAt": now + timedelta(days=7),
            }
        )
        db.videoWorkerHeartbeats.insert_one(
            {
                "_id": "admin-overview-worker",
                "status": "running",
                "transcriptionProvider": "faster_whisper",
                "transcriptionModel": "tiny",
                "modelWarmed": True,
                "expiresAt": now + timedelta(minutes=1),
                "updatedAt": now,
            }
        )
        db.pushWorkerHeartbeats.insert_one(
            {
                "_id": "admin-overview-push-worker",
                "status": "running",
                "provider": "fcm",
                "projectId": "test-firebase-project",
                "credentialsValidated": True,
                "expiresAt": now + timedelta(minutes=1),
                "updatedAt": now,
            }
        )
    overview = auth_client.get("/api/admin/overview")
    workers = auth_client.get("/api/employers/default/workers")
    worker_detail = auth_client.get(
        f"/api/employers/default/workers/{worker['userId']}"
    )
    worker_assignments = auth_client.get(
        "/api/employers/default/workers/"
        f"{worker['userId']}/support-assignments"
    )
    other_tenant_worker_detail = auth_client.get(
        f"/api/employers/acme/workers/{worker['userId']}"
    )
    other_tenant_worker_assignments = auth_client.get(
        "/api/employers/acme/workers/"
        f"{worker['userId']}/support-assignments"
    )
    panel = auth_client.get("/admin")
    missing_logout_csrf = auth_client.post("/api/auth/logout")
    logout = auth_client.post(
        "/api/auth/logout",
        headers={"X-CSRF-Token": csrf_token},
    )
    after_logout = auth_client.get("/api/admin/overview")
    assert missing_csrf.status_code == 403
    assert invitation.status_code == 201
    assert audit_events.status_code == 200
    assert other_tenant_audit.status_code == 403
    audit_payload = audit_events.get_json()
    assert audit_payload["pagination"]["total"] == 1
    audit_event = audit_payload["auditEvents"][0]
    assert audit_event["action"] == "admin.create_worker_invitation"
    assert audit_event["outcome"] == "success"
    assert audit_event["statusCode"] == 201
    assert audit_event["target"] == {"employer_key": "default"}
    assert "+905550004499" not in str(audit_event)
    with auth_app.app_context():
        stored_audit_event = get_db().adminAuditEvents.find_one(
            {"requestId": audit_event["requestId"]}
        )
        assert (
            stored_audit_event["purgeAt"]
            - stored_audit_event["createdAt"]
        ).days == 365
        assert any(
            index.get("expireAfterSeconds") == 0
            for index in get_db().adminAuditEvents.index_information().values()
        )
    assert overview.status_code == 200
    overview_payload = overview.get_json()
    assert overview_payload["metrics"]["workers"] == 1
    assert overview_payload["operations"]["videoProcessing"] == {
        "activeWorkers": 1,
        "runtime": {
            "transcriptionProvider": "faster_whisper",
            "transcriptionModel": "tiny",
            "modelWarmed": True,
            "updatedAt": now.isoformat(timespec="milliseconds"),
        },
        "queue": {
            "queued": 0,
            "processing": 0,
            "completed": 0,
            "failed": 1,
        },
    }
    assert overview_payload["operations"]["pushNotifications"] == {
        "provider": "static",
        "activeWorkers": 1,
        "runtime": {
            "provider": "fcm",
            "projectId": "test-firebase-project",
            "credentialsValidated": True,
            "updatedAt": now.isoformat(timespec="milliseconds"),
        },
        "queue": {
            "queued": 0,
            "processing": 0,
            "sent": 0,
            "skipped": 0,
            "failed": 0,
        },
    }
    assert overview_payload["operations"][
        "videoSourceDeletionFailures"
    ] == 0
    assert workers.status_code == 200
    assert workers.get_json()["pagination"]["total"] == 1
    assert worker_detail.status_code == 200
    assert worker_detail.get_json()["worker"]["id"] == worker["userId"]
    assert worker_assignments.status_code == 200
    assert (
        worker_assignments.get_json()["supportAssignments"]["workerId"]
        == worker["userId"]
    )
    assert other_tenant_worker_detail.status_code == 403
    assert other_tenant_worker_assignments.status_code == 403
    assert panel.status_code == 200
    assert "İşveren Yönetimi" in panel.get_data(as_text=True)
    assert panel.headers["Content-Security-Policy"].startswith("default-src")
    assert missing_logout_csrf.status_code == 403
    assert logout.status_code == 204
    assert after_logout.status_code == 401
    assert any(
        "admin_session=;" in header
        for header in logout.headers.getlist("Set-Cookie")
    )


def test_employer_can_list_and_retry_own_failed_video_processing_job(
    auth_app,
    auth_client,
):
    worker = _authenticate_worker(
        auth_client,
        "+905554445577",
    )
    user_id = ObjectId(worker["userId"])
    video_id = ObjectId()
    job_id = ObjectId()
    now = datetime.now(UTC)
    upload_dir = Path(AuthTestConfig.UPLOAD_FOLDER) / str(user_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    source_path = upload_dir / "failed-video.mp4"
    source_path.write_bytes(b"failed video source")

    with auth_app.app_context():
        db = get_db()
        db.users.update_one(
            {"_id": user_id},
            {
                "$set": {
                    "latestVideoId": video_id,
                    "profileStatus": "video_processing_failed",
                    "videoStatus": "failed",
                }
            },
        )
        db.videos.insert_one(
            {
                "_id": video_id,
                "userId": user_id,
                "originalFilename": "failed-video.mp4",
                "storedPath": str(source_path),
                "status": "failed",
                "processingError": "transcription unavailable",
                "createdAt": now,
                "updatedAt": now,
            }
        )
        db.videoProcessingJobs.insert_one(
            {
                "_id": job_id,
                "videoId": video_id,
                "userId": user_id,
                "status": "failed",
                "attempts": 3,
                "maxAttempts": 3,
                "lastError": "transcription unavailable",
                "failedAt": now,
                "purgeAt": now + timedelta(days=7),
                "createdAt": now,
                "updatedAt": now,
            }
        )

    login = auth_client.post(
        "/api/admin/auth/login",
        json={
            "username": "admin",
            "password": "correct-password",
        },
    )
    assert login.status_code == 200
    csrf_token = auth_client.get_cookie("admin_csrf").value

    listed = auth_client.get(
        "/api/employers/default/video-processing-jobs?status=failed"
    )
    other_tenant = auth_client.get(
        "/api/employers/acme/video-processing-jobs?status=failed"
    )
    retry_url = (
        "/api/employers/default/video-processing-jobs/"
        f"{job_id}/retry"
    )
    missing_csrf = auth_client.post(retry_url)
    retried = auth_client.post(
        retry_url,
        headers={"X-CSRF-Token": csrf_token},
    )
    duplicate_retry = auth_client.post(
        retry_url,
        headers={"X-CSRF-Token": csrf_token},
    )

    assert listed.status_code == 200
    listed_payload = listed.get_json()
    assert listed_payload["pagination"]["total"] == 1
    assert listed_payload["videoProcessingJobs"][0]["id"] == str(job_id)
    assert (
        listed_payload["videoProcessingJobs"][0]["worker"]["phone"]
        == "+905554445577"
    )
    assert other_tenant.status_code == 403
    assert missing_csrf.status_code == 403
    assert retried.status_code == 200
    assert retried.get_json()["videoProcessingJob"]["status"] == "queued"
    assert duplicate_retry.status_code == 409

    with auth_app.app_context():
        db = get_db()
        stored_job = db.videoProcessingJobs.find_one({"_id": job_id})
        stored_video = db.videos.find_one({"_id": video_id})
        stored_user = db.users.find_one({"_id": user_id})
        assert stored_job["status"] == "queued"
        assert stored_job["attempts"] == 0
        assert stored_job["manualRetryCount"] == 1
        assert stored_job["manualRetriedBy"] == "admin"
        assert stored_job["manualRetryHistory"] == [
            {
                "requestedAt": stored_job["manualRetriedAt"],
                "requestedBy": "admin",
                "previousError": "transcription unavailable",
                "previousAttempts": 3,
            }
        ]
        assert "purgeAt" not in stored_job
        assert "lastError" not in stored_job
        assert stored_video["status"] == "processing"
        assert "processingError" not in stored_video
        assert stored_user["profileStatus"] == "video_processing"
        assert stored_user["videoStatus"] == "processing"
        audit_event = db.adminAuditEvents.find_one(
            {
                "action": "admin.retry_video_processing_job",
                "statusCode": 200,
            }
        )
        assert audit_event["target"]["job_id"] == str(job_id)


def test_employer_can_remediate_only_safe_invalid_phone_workers(
    auth_app,
    auth_client,
):
    now = datetime.now(UTC)
    correctable_id = ObjectId()
    cleanup_id = ObjectId()
    blocked_id = ObjectId()
    other_tenant_id = ObjectId()
    existing_phone_id = ObjectId()
    application_id = ObjectId()
    with auth_app.app_context():
        db = get_db()
        db.users.insert_many(
            [
                {
                    "_id": correctable_id,
                    "name": "Düzeltilecek Kayıt",
                    "phone": "+90555123456",
                    "employerKey": "default",
                    "profileStatus": "registered",
                    "videoStatus": "not_uploaded",
                    "createdAt": now,
                    "updatedAt": now,
                },
                {
                    "_id": cleanup_id,
                    "name": "Temizlenecek Kayıt",
                    "phone": "+90555123457",
                    "employerKey": "default",
                    "profileStatus": "registered",
                    "videoStatus": "not_uploaded",
                    "createdAt": now,
                    "updatedAt": now,
                },
                {
                    "_id": blocked_id,
                    "name": "Doğrulanmış Eski Kayıt",
                    "phone": "+90555123458",
                    "employerKey": "default",
                    "phoneVerifiedAt": now,
                    "profileStatus": "registered",
                    "videoStatus": "not_uploaded",
                    "createdAt": now,
                    "updatedAt": now,
                },
                {
                    "_id": other_tenant_id,
                    "name": "Başka İşveren",
                    "phone": "+90555123459",
                    "employerKey": "acme",
                    "profileStatus": "registered",
                    "videoStatus": "not_uploaded",
                    "createdAt": now,
                    "updatedAt": now,
                },
                {
                    "_id": existing_phone_id,
                    "name": "Geçerli Kayıt",
                    "phone": "+905559998877",
                    "employerKey": "default",
                    "profileStatus": "registered",
                    "videoStatus": "not_uploaded",
                    "createdAt": now,
                    "updatedAt": now,
                },
            ]
        )
        db.jobApplications.insert_one(
            {
                "_id": application_id,
                "userId": cleanup_id,
                "employerKey": "default",
                "status": "submitted",
                "candidate": {
                    "name": "Temizlenecek Kayıt",
                    "phone": "+90555123457",
                    "profileStatus": "registered",
                    "skills": [],
                    "summary": None,
                },
                "coverNote": "Kişisel not",
                "statusHistory": [
                    {"status": "submitted", "changedAt": now}
                ],
                "createdAt": now,
                "updatedAt": now,
            }
        )
        db.workerQuestions.insert_one(
            {
                "userId": cleanup_id,
                "employerKey": "default",
                "question": "Eski soru",
                "status": "pending",
                "createdAt": now,
                "updatedAt": now,
            }
        )

    login = auth_client.post(
        "/api/admin/auth/login",
        json={
            "username": "admin",
            "password": "correct-password",
        },
    )
    assert login.status_code == 200
    csrf_token = auth_client.get_cookie("admin_csrf").value
    headers = {"X-CSRF-Token": csrf_token}

    listed = auth_client.get(
        "/api/employers/default/data-hygiene/workers"
    )
    other_tenant = auth_client.get(
        "/api/employers/acme/data-hygiene/workers"
    )
    correction_url = (
        "/api/employers/default/data-hygiene/workers/"
        f"{correctable_id}/phone"
    )
    missing_csrf = auth_client.patch(
        correction_url,
        json={"phone": "+905551234567"},
    )
    invalid_phone = auth_client.patch(
        correction_url,
        headers=headers,
        json={"phone": "123"},
    )
    duplicate_phone = auth_client.patch(
        correction_url,
        headers=headers,
        json={"phone": "+905559998877"},
    )
    corrected = auth_client.patch(
        correction_url,
        headers=headers,
        json={"phone": "0555 123 45 67"},
    )

    cleanup_url = (
        "/api/employers/default/data-hygiene/workers/"
        f"{cleanup_id}"
    )
    missing_confirmation = auth_client.delete(
        cleanup_url,
        headers=headers,
        json={"confirmation": "YANLIS"},
    )
    blocked_cleanup = auth_client.delete(
        "/api/employers/default/data-hygiene/workers/"
        f"{blocked_id}",
        headers=headers,
        json={"confirmation": "TEMIZLE"},
    )
    cleaned = auth_client.delete(
        cleanup_url,
        headers=headers,
        json={"confirmation": "TEMIZLE"},
    )

    assert listed.status_code == 200
    listed_payload = listed.get_json()
    assert listed_payload["pagination"]["total"] == 3
    listed_workers = {
        item["id"]: item for item in listed_payload["workers"]
    }
    assert listed_workers[str(correctable_id)]["canCorrectPhone"] is True
    assert listed_workers[str(cleanup_id)]["canCleanup"] is True
    assert listed_workers[str(cleanup_id)]["applicationCount"] == 1
    assert listed_workers[str(cleanup_id)]["supportRecordCount"] == 1
    assert listed_workers[str(blocked_id)]["canCorrectPhone"] is False
    assert listed_workers[str(blocked_id)]["cleanupBlockers"] == [
        "phone_verified"
    ]
    assert other_tenant.status_code == 403
    assert missing_csrf.status_code == 403
    assert invalid_phone.status_code == 400
    assert duplicate_phone.status_code == 409
    assert corrected.status_code == 200
    assert corrected.get_json()["worker"]["phone"] == "+905551234567"
    assert corrected.get_json()["worker"]["phoneVerifiedAt"] is None
    assert missing_confirmation.status_code == 400
    assert blocked_cleanup.status_code == 409
    assert cleaned.status_code == 204

    with auth_app.app_context():
        db = get_db()
        report = build_data_hygiene_report(
            db,
            employer_key="default",
        )
        assert report["invalidPhoneWorkers"] == 1
        assert report["truncated"] is False
        assert all(
            item["maskedPhone"].startswith("+90")
            for item in report["workers"]
        )
        assert "+90555123458" not in str(report)
        corrected_worker = db.users.find_one(
            {"_id": correctable_id}
        )
        assert corrected_worker["phone"] == "+905551234567"
        assert db.users.find_one({"_id": cleanup_id}) is None
        assert db.workerQuestions.count_documents(
            {"userId": cleanup_id}
        ) == 0
        application = db.jobApplications.find_one(
            {"_id": application_id}
        )
        assert application["candidate"]["name"] == "Silinen kullanıcı"
        assert application["candidate"]["phone"] is None
        assert application["coverNote"] == ""
        assert application["accountDeletedAt"] is not None
        actions = {
            event["action"]
            for event in db.adminAuditEvents.find(
                {
                    "action": {
                        "$in": [
                            "admin.correct_invalid_phone_worker",
                            "admin.cleanup_invalid_phone_worker",
                        ]
                    },
                    "outcome": "success",
                }
            )
        }
        assert actions == {
            "admin.correct_invalid_phone_worker",
            "admin.cleanup_invalid_phone_worker",
        }


def test_production_startup_rejects_unsafe_configuration():
    class UnsafeProductionConfig(AuthTestConfig):
        APP_ENV = "production"
        SECRET_KEY = "short"
        STRICT_DATA_HYGIENE = False
        VIDEO_PROCESSING_MODE = "thread"
        VIDEO_WORKER_WARMUP_MODEL = False
        FFPROBE_PATH = "ffprobe"
        VIDEO_DELETE_SOURCE_AFTER_PROCESSING = False
        VIDEO_UPLOAD_RATE_LIMIT_WINDOW_SECONDS = 1
        VIDEO_UPLOAD_MAX_REQUESTS = 0
        VIDEO_JOB_RETENTION_SECONDS = 1
        WORKER_QUESTION_RATE_LIMIT_WINDOW_SECONDS = 1
        WORKER_QUESTION_MAX_REQUESTS = 0
        ADMIN_AUDIT_RETENTION_DAYS = 1
        ACCOUNT_DELETION_AUDIT_RETENTION_DAYS = 1
        REQUIRE_IDEMPOTENCY_KEY = False
        IDEMPOTENCY_RETENTION_SECONDS = 1
        IDEMPOTENCY_PROCESSING_TIMEOUT_SECONDS = 1
        IDEMPOTENCY_UPLOAD_PROCESSING_TIMEOUT_SECONDS = 1
        SMS_PROVIDER = "static"
        OTP_STATIC_CODE = "123456"
        OTP_EXPOSE_CODE = True
        ADMIN_PASSWORD = "plaintext"
        ADMIN_PASSWORD_HASH = ""
        MOBILE_MIN_SUPPORTED_VERSION_CODE = 0
        MOBILE_LATEST_VERSION_CODE = -1
        MOBILE_MAINTENANCE_MODE = True
        MOBILE_MAINTENANCE_MESSAGE = ""
        MOBILE_UPDATE_MESSAGE = ""
        MOBILE_UPDATE_URL = "http://example.com/app"
        PRIVACY_POLICY_URL = "http://example.com/privacy"
        VIDEO_CONSENT_VERSION = ""
        REQUIRE_VIDEO_CONSENT = False
        PUSH_PROVIDER = "disabled"
        FCM_PROJECT_ID = ""
        PUSH_WORKER_VALIDATE_CREDENTIALS = False
        PUSH_JOB_MAX_ATTEMPTS = 0
        PUSH_JOB_LEASE_SECONDS = 1
        PUSH_JOB_RETRY_BASE_SECONDS = 0
        PUSH_JOB_RETRY_MAX_SECONDS = 1
        PUSH_JOB_RETENTION_SECONDS = 1
        PUSH_REGISTRATION_RETENTION_DAYS = 0
        PUSH_MAX_ACTIVE_REGISTRATIONS_PER_WORKER = 0
        PUSH_MAX_STORED_REGISTRATIONS_PER_WORKER = 0

    with pytest.raises(RuntimeError) as error:
        create_app(UnsafeProductionConfig)

    message = str(error.value)
    assert "SECRET_KEY" in message
    assert "MONGO_URI" in message
    assert "STRICT_DATA_HYGIENE" in message
    assert "TRUSTED_HOSTS" in message
    assert "VIDEO_PROCESSING_MODE" in message
    assert "VIDEO_WORKER_WARMUP_MODEL" in message
    assert "FFPROBE_PATH" in message
    assert "VIDEO_DELETE_SOURCE_AFTER_PROCESSING" in message
    assert "VIDEO_UPLOAD_RATE_LIMIT_WINDOW_SECONDS" in message
    assert "VIDEO_UPLOAD_MAX_REQUESTS" in message
    assert "VIDEO_JOB_RETENTION_SECONDS" in message
    assert "WORKER_QUESTION_RATE_LIMIT_WINDOW_SECONDS" in message
    assert "WORKER_QUESTION_MAX_REQUESTS" in message
    assert "ADMIN_AUDIT_RETENTION_DAYS" in message
    assert "ACCOUNT_DELETION_AUDIT_RETENTION_DAYS" in message
    assert "REQUIRE_IDEMPOTENCY_KEY" in message
    assert "IDEMPOTENCY_RETENTION_SECONDS" in message
    assert "IDEMPOTENCY_PROCESSING_TIMEOUT_SECONDS" in message
    assert "IDEMPOTENCY_UPLOAD_PROCESSING_TIMEOUT_SECONDS" in message
    assert "SMS_PROVIDER" in message
    assert "OTP_STATIC_CODE" in message
    assert "ADMIN_PASSWORD_HASH" in message
    assert "TRANSCRIPTION_PROVIDER" in message
    assert "MOBILE_MIN_SUPPORTED_VERSION_CODE" in message
    assert "MOBILE_LATEST_VERSION_CODE" in message
    assert "MOBILE_MAINTENANCE_MESSAGE" in message
    assert "MOBILE_UPDATE_MESSAGE" in message
    assert "MOBILE_UPDATE_URL" in message
    assert "PRIVACY_POLICY_URL" in message
    assert "VIDEO_CONSENT_VERSION" in message
    assert "REQUIRE_VIDEO_CONSENT" in message
    assert "PUSH_PROVIDER" in message
    assert "FCM_PROJECT_ID" in message
    assert "PUSH_WORKER_VALIDATE_CREDENTIALS" in message
    assert "PUSH_JOB_MAX_ATTEMPTS" in message
    assert "PUSH_JOB_LEASE_SECONDS" in message
    assert "PUSH_JOB_RETRY_BASE_SECONDS" in message
    assert "PUSH_JOB_RETRY_MAX_SECONDS" in message
    assert "PUSH_JOB_RETENTION_SECONDS" in message
    assert "PUSH_REGISTRATION_RETENTION_DAYS" in message
    assert "PUSH_MAX_ACTIVE_REGISTRATIONS_PER_WORKER" in message
    assert "PUSH_MAX_STORED_REGISTRATIONS_PER_WORKER" in message


def test_production_startup_rejects_missing_twilio_credentials():
    class MissingSmsCredentialsConfig(AuthTestConfig):
        APP_ENV = "production"
        SECRET_KEY = "a-unique-production-secret-with-more-than-32-characters"
        MONGO_URI = "mongodb://user:password@mongo.example:27017/test?tls=true"
        TRUSTED_HOSTS = ["api.example.com"]
        VIDEO_PROCESSING_MODE = "worker"
        SMS_PROVIDER = "twilio"
        TWILIO_ACCOUNT_SID = ""
        TWILIO_AUTH_TOKEN = ""
        TWILIO_FROM_NUMBER = ""
        OTP_STATIC_CODE = ""
        OTP_EXPOSE_CODE = False
        ADMIN_PASSWORD = ""
        ADMIN_PASSWORD_HASH = "scrypt:test-hash"
        TRANSCRIPTION_PROVIDER = "faster_whisper"
        VIDEO_VALIDATE_CONTENT = True
        JOB_RECOMMENDATION_FALLBACK_ENABLED = False
        REQUIRE_IDEMPOTENCY_KEY = True

    with pytest.raises(RuntimeError, match="Twilio credentials"):
        create_app(MissingSmsCredentialsConfig)


@pytest.mark.parametrize(
    ("mongo_uri", "expected_message"),
    [
        (
            "mongodb://mongo.example:27017/test",
            "MONGO_URI must enable TLS",
        ),
        (
            "mongodb://mongo.example:27017/test?tls=true",
            "MONGO_URI must include an authenticated identity",
        ),
        (
            "mongodb+srv://user:password@cluster.example/test?tls=false",
            "MONGO_URI must enable TLS",
        ),
    ],
)
def test_production_startup_rejects_insecure_mongo_uri(
    mongo_uri, expected_message
):
    class ProductionConfig(AuthTestConfig):
        APP_ENV = "production"
        SECRET_KEY = "a-unique-production-secret-with-more-than-32-characters"
        TRUSTED_HOSTS = ["api.example.com"]
        VIDEO_PROCESSING_MODE = "worker"
        SMS_PROVIDER = "twilio"
        TWILIO_ACCOUNT_SID = "AC-test"
        TWILIO_AUTH_TOKEN = "test-token"
        TWILIO_FROM_NUMBER = "+15550001111"
        OTP_STATIC_CODE = ""
        OTP_EXPOSE_CODE = False
        ADMIN_PASSWORD = ""
        ADMIN_PASSWORD_HASH = "scrypt:test-hash"
        TRANSCRIPTION_PROVIDER = "faster_whisper"
        VIDEO_VALIDATE_CONTENT = True
        JOB_RECOMMENDATION_FALLBACK_ENABLED = False

    config = type(
        "MongoProductionConfig",
        (ProductionConfig,),
        {"MONGO_URI": mongo_uri},
    )

    with pytest.raises(RuntimeError, match=expected_message):
        create_app(config)


def test_production_startup_accepts_complete_configuration():
    class SafeProductionConfig(AuthTestConfig):
        APP_ENV = "production"
        SECRET_KEY = "a-unique-production-secret-with-more-than-32-characters"
        MONGO_URI = "mongodb://user:password@mongo.example:27017/test?tls=true"
        TRUSTED_HOSTS = ["api.example.com"]
        VIDEO_PROCESSING_MODE = "worker"
        SMS_PROVIDER = "twilio"
        TWILIO_ACCOUNT_SID = "AC-test"
        TWILIO_AUTH_TOKEN = "test-token"
        TWILIO_FROM_NUMBER = "+15550001111"
        OTP_STATIC_CODE = ""
        OTP_EXPOSE_CODE = False
        ADMIN_PASSWORD = ""
        ADMIN_PASSWORD_HASH = generate_password_hash(
            "a-unique-production-admin-password"
        )
        TRANSCRIPTION_PROVIDER = "faster_whisper"
        VIDEO_VALIDATE_CONTENT = True
        JOB_RECOMMENDATION_FALLBACK_ENABLED = False
        REQUIRE_IDEMPOTENCY_KEY = True
        REQUIRE_VIDEO_CONSENT = True
        PRIVACY_POLICY_URL = (
            "https://privacy.yediyirmidort.com/video"
        )
        PUSH_PROVIDER = "fcm"
        FCM_PROJECT_ID = "test-firebase-project"

    class InvalidHashProductionConfig(SafeProductionConfig):
        ADMIN_PASSWORD_HASH = "scrypt:test-hash"

    with pytest.raises(
        RuntimeError,
        match="valid Werkzeug scrypt hash",
    ):
        create_app(InvalidHashProductionConfig)

    app = create_app(SafeProductionConfig)

    assert app.config["APP_ENV"] == "production"


def test_invited_worker_is_assigned_to_employer_after_phone_verification(
    auth_app, auth_client
):
    auth_app.config["ADMIN_EMPLOYER_KEY"] = "acme"
    login = auth_client.post(
        "/api/admin/auth/login",
        json={"username": "admin", "password": "correct-password"},
    )
    csrf_token = auth_client.get_cookie("admin_csrf").value
    invitation = auth_client.post(
        "/api/employers/acme/worker-invitations",
        headers={"X-CSRF-Token": csrf_token},
        json={"phone": "0555 700 80 90"},
    )
    duplicate = auth_client.post(
        "/api/employers/acme/worker-invitations",
        headers={"X-CSRF-Token": csrf_token},
        json={"phone": "+905557008090"},
    )

    assert invitation.status_code == 201
    assert invitation.get_json()["workerInvitation"]["phone"] == "+905557008090"
    assert duplicate.status_code == 409

    pending = auth_client.get(
        "/api/employers/acme/worker-invitations?status=pending",
    )
    assert len(pending.get_json()["workerInvitations"]) == 1

    worker = _authenticate_worker(auth_client, "+905557008090")
    assert worker["auth"]["user"]["employerKey"] == "acme"

    dashboard = auth_client.get(
        f"/api/users/{worker['userId']}/dashboard",
        headers=_bearer(worker["token"]),
    )
    accepted = auth_client.get(
        "/api/employers/acme/worker-invitations?status=accepted",
    )
    workers = auth_client.get(
        "/api/employers/acme/workers",
    )

    assert dashboard.status_code == 200
    assert dashboard.get_json()["workerHub"]["employerKey"] == "acme"
    assert len(accepted.get_json()["workerInvitations"]) == 1
    assert workers.get_json()["pagination"]["total"] == 1


def test_worker_device_registration_is_owner_scoped(auth_client):
    owner = _authenticate_worker(
        auth_client,
        "+905557008101",
    )
    other = _authenticate_worker(
        auth_client,
        "+905557008102",
    )
    installation_id = "88888888-8888-4888-8888-888888888888"
    url = (
        f"/api/users/{owner['userId']}/devices/"
        f"{installation_id}"
    )
    payload = {
        "fid": "owner-scoped-device-fid-0000001",
        "platform": "android",
        "appVersionCode": 1,
        "appVersionName": "1.0",
    }

    unauthenticated = auth_client.put(url, json=payload)
    other_worker = auth_client.put(
        url,
        headers=_bearer(other["token"]),
        json=payload,
    )
    own = auth_client.put(
        url,
        headers=_bearer(owner["token"]),
        json=payload,
    )
    login = auth_client.post(
        "/api/admin/auth/login",
        json={
            "username": "admin",
            "password": "correct-password",
        },
    )
    employer = auth_client.put(url, json=payload)

    assert unauthenticated.status_code == 401
    assert other_worker.status_code == 403
    assert own.status_code == 200
    assert login.status_code == 200
    assert employer.status_code == 403


def test_worker_video_consent_is_owner_scoped(auth_client):
    owner = _authenticate_worker(
        auth_client,
        "+905557008105",
    )
    other = _authenticate_worker(
        auth_client,
        "+905557008106",
    )
    url = (
        f"/api/users/{owner['userId']}"
        "/consents/video-processing"
    )
    payload = {
        "version": "video-processing-v1",
        "accepted": True,
    }

    unauthenticated = auth_client.put(url, json=payload)
    other_worker = auth_client.put(
        url,
        headers=_bearer(other["token"]),
        json=payload,
    )
    own = auth_client.put(
        url,
        headers=_bearer(owner["token"]),
        json=payload,
    )
    login = auth_client.post(
        "/api/admin/auth/login",
        json={
            "username": "admin",
            "password": "correct-password",
        },
    )
    employer = auth_client.delete(url)

    assert unauthenticated.status_code == 401
    assert other_worker.status_code == 403
    assert own.status_code == 200
    assert login.status_code == 200
    assert employer.status_code == 403


def test_worker_profile_review_is_owner_scoped(auth_client):
    owner = _authenticate_worker(
        auth_client,
        "+905557008103",
    )
    other = _authenticate_worker(
        auth_client,
        "+905557008104",
    )
    user_id = owner["userId"]
    upload = auth_client.post(
        f"/api/users/{user_id}/videos",
        headers=_bearer(owner["token"]),
        data={
            "video": (
                BytesIO(b"profile ownership"),
                "profile.mp4",
            )
        },
        content_type="multipart/form-data",
    )
    url = f"/api/users/{user_id}/profile-review"

    unauthenticated = auth_client.put(
        url,
        json={"name": "Test Kullanıcı"},
    )
    other_worker = auth_client.put(
        url,
        headers=_bearer(other["token"]),
        json={"name": "Test Kullanıcı"},
    )
    own = auth_client.put(
        url,
        headers=_bearer(owner["token"]),
        json={"name": "Test Kullanıcı"},
    )
    login = auth_client.post(
        "/api/admin/auth/login",
        json={
            "username": "admin",
            "password": "correct-password",
        },
    )
    employer = auth_client.put(
        url,
        json={"name": "Test Kullanıcı"},
    )

    assert upload.status_code == 201
    assert unauthenticated.status_code == 401
    assert other_worker.status_code == 403
    assert own.status_code == 200
    assert login.status_code == 200
    assert employer.status_code == 403


def _authenticate_worker(client, phone: str) -> dict:
    challenge_response = client.post(
        "/api/auth/otp/request", json={"phone": phone}
    )
    assert challenge_response.status_code == 202
    challenge = challenge_response.get_json()

    verify_response = client.post(
        "/api/auth/otp/verify",
        json={
            "challengeId": challenge["challengeId"],
            "phone": challenge["phone"],
            "code": "123456",
        },
    )
    assert verify_response.status_code == 200
    auth = verify_response.get_json()
    return {
        "challenge": challenge,
        "auth": auth,
        "token": auth["accessToken"],
        "userId": auth["user"]["id"],
    }


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _clean_database(db) -> None:
    for collection in COLLECTIONS:
        db[collection].delete_many({})
