import hashlib
import sys
from io import BytesIO
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event

import pytest
from bson import ObjectId

from app import create_app
from app.db import get_client, get_db
from app.services.video_processing import (
    claim_video_job,
    cleanup_pending_video_sources,
    prepare_video_worker_runtime,
    process_claimed_video_job,
    run_video_worker,
)
from app.services.transcription import transcribe_video
from app.services.push_notifications import (
    PermanentDeviceRegistrationError,
    claim_push_job,
    enqueue_worker_push,
    prepare_push_worker_runtime,
    process_claimed_push_job,
    run_push_worker,
)
from app.services.production_preflight import (
    run_production_preflight,
)


class TestConfig:
    TESTING = True
    AUTH_REQUIRED = False
    SECRET_KEY = "test-secret-key"
    MONGO_URI = "mongodb://localhost:27017"
    MONGO_DB_NAME = "yedi_yirmi_dort_test"
    STRICT_DATA_HYGIENE = False
    UPLOAD_FOLDER = "/tmp/yedi_yirmi_dort_test_uploads"
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024
    ALLOWED_VIDEO_EXTENSIONS = {"mp4"}
    VIDEO_VALIDATE_CONTENT = False
    VIDEO_DELETE_SOURCE_AFTER_PROCESSING = True
    VIDEO_PROCESSING_INLINE = True
    VIDEO_JOB_RETENTION_SECONDS = 604800
    VIDEO_WORKER_WARMUP_MODEL = False
    ACCOUNT_DELETION_AUDIT_RETENTION_DAYS = 365
    VIDEO_UPLOAD_RATE_LIMIT_WINDOW_SECONDS = 86400
    VIDEO_UPLOAD_MAX_REQUESTS = 3
    REQUIRE_VIDEO_CONSENT = False
    VIDEO_CONSENT_VERSION = "video-processing-v1"
    PRIVACY_POLICY_URL = "https://example.com/privacy"
    TRANSCRIPTION_PROVIDER = "static"
    TRANSCRIPTION_STATIC_TEXT = (
        "Adım Mehmet Yılmaz. Kaynak işlerinde deneyimliyim. B sınıfı ehliyetim var, araç kullanabilirim. "
        "Vardiyalı çalışmaya müsaitim ve ekip çalışmasına uyumluyum."
    )
    JOB_RECOMMENDATION_FALLBACK_ENABLED = True
    WORKER_QUESTION_RATE_LIMIT_WINDOW_SECONDS = 3600
    WORKER_QUESTION_MAX_REQUESTS = 20
    REQUIRE_IDEMPOTENCY_KEY = False
    IDEMPOTENCY_RETENTION_SECONDS = 86400
    IDEMPOTENCY_PROCESSING_TIMEOUT_SECONDS = 120
    IDEMPOTENCY_UPLOAD_PROCESSING_TIMEOUT_SECONDS = 900
    PUSH_PROVIDER = "static"
    FCM_PROJECT_ID = ""
    PUSH_JOB_MAX_ATTEMPTS = 3
    PUSH_JOB_LEASE_SECONDS = 60
    PUSH_JOB_RETRY_BASE_SECONDS = 1
    PUSH_JOB_RETRY_MAX_SECONDS = 30
    PUSH_JOB_RETENTION_SECONDS = 86400
    PUSH_WORKER_POLL_SECONDS = 0.01
    PUSH_WORKER_HEARTBEAT_SECONDS = 1
    PUSH_WORKER_VALIDATE_CREDENTIALS = False
    PUSH_REGISTRATION_RETENTION_DAYS = 90
    PUSH_MAX_ACTIVE_REGISTRATIONS_PER_WORKER = 5
    PUSH_MAX_STORED_REGISTRATIONS_PER_WORKER = 20


@pytest.fixture()
def app():
    app = create_app(TestConfig)
    with app.app_context():
        db = get_db()
        db.users.delete_many({})
        db.workerConsents.delete_many({})
        db.videos.delete_many({})
        db.videoTranscripts.delete_many({})
        db.videoProcessingJobs.delete_many({})
        db.videoWorkerHeartbeats.delete_many({})
        db.candidateProfiles.delete_many({})
        db.jobRecommendations.delete_many({})
        db.jobPostings.delete_many({})
        db.jobApplications.delete_many({})
        db.jobHiringSlots.delete_many({})
        db.workerSupportConfigs.delete_many({})
        db.workerSupportAssignments.delete_many({})
        db.workerInvitations.delete_many({})
        db.workerQuestions.delete_many({})
        db.workerAssessmentResults.delete_many({})
        db.workerTrainingProgress.delete_many({})
        db.workerShuttleRequests.delete_many({})
        db.actionRateLimits.delete_many({})
        db.idempotencyRecords.delete_many({})
        db.accountDeletionRecords.delete_many({})
        db.workerPushRegistrations.delete_many({})
        db.pushNotificationJobs.delete_many({})
        db.pushWorkerHeartbeats.delete_many({})
    yield app
    with app.app_context():
        db = get_db()
        db.users.delete_many({})
        db.workerConsents.delete_many({})
        db.videos.delete_many({})
        db.videoTranscripts.delete_many({})
        db.videoProcessingJobs.delete_many({})
        db.videoWorkerHeartbeats.delete_many({})
        db.candidateProfiles.delete_many({})
        db.jobRecommendations.delete_many({})
        db.jobPostings.delete_many({})
        db.jobApplications.delete_many({})
        db.jobHiringSlots.delete_many({})
        db.workerSupportConfigs.delete_many({})
        db.workerSupportAssignments.delete_many({})
        db.workerInvitations.delete_many({})
        db.workerQuestions.delete_many({})
        db.workerAssessmentResults.delete_many({})
        db.workerTrainingProgress.delete_many({})
        db.workerShuttleRequests.delete_many({})
        db.actionRateLimits.delete_many({})
        db.idempotencyRecords.delete_many({})
        db.accountDeletionRecords.delete_many({})
        db.workerPushRegistrations.delete_many({})
        db.pushNotificationJobs.delete_many({})
        db.pushWorkerHeartbeats.delete_many({})
    upload_dir = Path(TestConfig.UPLOAD_FOLDER)
    if upload_dir.exists():
        for path in upload_dir.rglob("*"):
            if path.is_file():
                path.unlink()


@pytest.fixture()
def client(app):
    return app.test_client()


def test_register_user_and_get_dashboard(client):
    rejected_name = client.post(
        "/api/users",
        json={
            "phone": "+905551112232",
            "name": "Formdan Gelen İsim",
        },
    )
    response = client.post("/api/users", json={"phone": "+905551112233"})

    assert rejected_name.status_code == 400
    assert response.status_code == 201
    user = response.get_json()["user"]
    assert user["name"] == ""
    assert user["nameStatus"] == "pending_video"
    assert user["profileReviewStatus"] == "pending_video"
    assert user["profileStatus"] == "registered"

    dashboard = client.get(f"/api/users/{user['id']}/dashboard")

    assert dashboard.status_code == 200
    payload = dashboard.get_json()
    assert payload["user"]["id"] == user["id"]
    assert payload["latestVideo"] is None
    assert payload["latestTranscript"] is None
    assert payload["candidateProfile"] is None
    assert payload["recommendedJobs"] == []
    assert payload["jobApplications"] == []
    assert payload["workerHub"]["assessments"]
    assert payload["workerHub"]["assessments"][0]["questions"]
    assert payload["workerHub"]["trainings"]
    assert payload["workerHub"]["trainings"][0]["modules"]
    assert payload["workerHub"]["usefulInfo"]
    assert payload["workerHub"]["shuttle"]["enabled"] is True
    assert payload["pendingQuestionCount"] == 0


def test_employer_worker_detail_aggregates_tenant_scoped_progress(
    app, client
):
    worker = client.post(
        "/api/users",
        json={
            "phone": "+905551112299",
            "employerKey": "acme",
        },
    ).get_json()["user"]
    worker_id = ObjectId(worker["id"])
    video_id = ObjectId()
    now = datetime.now(UTC)

    with app.app_context():
        db = get_db()
        db.workerConsents.insert_one(
            {
                "userId": worker_id,
                "type": "video_processing",
                "version": "video-processing-v1",
                "status": "accepted",
                "policyUrl": "https://example.com/privacy",
                "acceptedAt": now,
                "revokedAt": None,
                "createdAt": now,
                "updatedAt": now,
            }
        )
        db.users.update_one(
            {"_id": worker_id},
            {
                "$set": {
                    "name": "Ayşe Demir",
                    "nameStatus": "inferred_from_video",
                    "profileStatus": "profile_ready",
                    "videoStatus": "completed",
                    "latestVideoId": video_id,
                }
            },
        )
        db.candidateProfiles.insert_one(
            {
                "userId": worker_id,
                "latestVideoId": video_id,
                "name": "Ayşe Demir",
                "summary": "Depo operasyonlarında deneyimli.",
                "skills": ["depo", "forklift"],
                "preferredRoles": ["Depo Operatörü"],
                "availability": "Hemen",
                "confidence": 0.91,
                "warnings": [],
                "createdAt": now,
                "updatedAt": now,
            }
        )
        db.workerAssessmentResults.insert_one(
            {
                "userId": worker_id,
                "employerKey": "acme",
                "assessmentId": "safety",
                "title": "İş Güvenliği",
                "status": "completed",
                "score": 80,
                "passScore": 70,
                "passed": True,
                "answers": [],
                "completedAt": now,
            }
        )
        db.workerTrainingProgress.insert_one(
            {
                "userId": worker_id,
                "employerKey": "acme",
                "trainingId": "orientation",
                "title": "Oryantasyon",
                "status": "completed",
                "progressPercent": 100,
                "completedModules": ["site"],
                "completedAt": now,
            }
        )
        db.workerShuttleRequests.insert_one(
            {
                "userId": worker_id,
                "employerKey": "acme",
                "routeId": "route-1",
                "routeName": "Merkez",
                "pickupWindow": "07:00 - 07:30",
                "pickupNote": "Ana durak",
                "status": "confirmed",
                "decisionNote": "Listeye eklendi.",
                "createdAt": now,
                "updatedAt": now,
            }
        )
        db.workerQuestions.insert_many(
            [
                {
                    "userId": worker_id,
                    "employerKey": "acme",
                    "question": "Servis nereden kalkıyor?",
                    "answer": "Merkez durağından.",
                    "status": "answered",
                    "createdAt": now,
                    "updatedAt": now,
                },
                {
                    "userId": worker_id,
                    "employerKey": "other",
                    "question": "Başka işverene ait kayıt",
                    "answer": "Görünmemeli.",
                    "status": "answered",
                    "createdAt": now,
                    "updatedAt": now,
                },
            ]
        )
        db.jobApplications.insert_one(
            {
                "userId": worker_id,
                "employerKey": "acme",
                "status": "reviewing",
                "job": {
                    "title": "Depo Operatörü",
                    "company": "ACME",
                    "location": "Kocaeli",
                    "matchScore": 85,
                },
                "candidate": {
                    "name": "Ayşe Demir",
                    "phone": "+905551112299",
                },
                "statusHistory": [],
                "createdAt": now,
                "updatedAt": now,
            }
        )

    response = client.get(
        f"/api/employers/acme/workers/{worker['id']}"
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["worker"]["name"] == "Ayşe Demir"
    assert payload["worker"]["profileReviewStatus"] == "pending"
    assert payload["videoConsent"]["status"] == "accepted"
    assert (
        payload["videoConsent"]["version"]
        == "video-processing-v1"
    )
    assert payload["profile"]["skills"] == ["depo", "forklift"]
    assert payload["assessmentResults"][0]["score"] == 80
    assert payload["trainingProgress"][0]["progressPercent"] == 100
    assert payload["shuttleRequest"]["status"] == "confirmed"
    assert len(payload["recentQuestions"]) == 1
    assert payload["recentQuestions"][0]["question"] == (
        "Servis nereden kalkıyor?"
    )
    assert payload["applications"][0]["status"] == "reviewing"
    assert client.get(
        f"/api/employers/other/workers/{worker['id']}"
    ).status_code == 404
    assert client.get(
        "/api/employers/acme/workers/not-an-id"
    ).status_code == 400


def test_worker_mutation_idempotency_replays_without_duplicate_side_effects(
    app, client
):
    app.config["REQUIRE_IDEMPOTENCY_KEY"] = True
    user = client.post(
        "/api/users", json={"phone": "+905551112244"}
    ).get_json()["user"]
    path = f"/api/users/{user['id']}/questions"
    headers = {"Idempotency-Key": "question-request-0001"}

    first = client.post(
        path,
        headers=headers,
        json={"question": "Servis saatim nedir?"},
    )
    replay = client.post(
        path,
        headers=headers,
        json={"question": "Servis saatim nedir?"},
    )
    conflicting = client.post(
        path,
        headers=headers,
        json={"question": "Maaş günüm nedir?"},
    )
    missing = client.post(
        path,
        json={"question": "Anahtar olmadan gönderim"},
    )
    invalid = client.post(
        path,
        headers={"Idempotency-Key": "short"},
        json={"question": "Geçersiz anahtar"},
    )

    assert first.status_code == 201
    assert first.headers["Idempotency-Replayed"] == "false"
    assert replay.status_code == 201
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert replay.get_json() == first.get_json()
    assert conflicting.status_code == 409
    assert missing.status_code == 400
    assert invalid.status_code == 400

    with app.app_context():
        db = get_db()
        assert db.workerQuestions.count_documents(
            {"userId": ObjectId(user["id"])}
        ) == 1
        record = db.idempotencyRecords.find_one(
            {"idempotencyKey": headers["Idempotency-Key"]}
        )
        assert record["status"] == "completed"
        assert (
            record["expiresAt"] - record["updatedAt"]
        ).total_seconds() == 86400
        assert any(
            index.get("expireAfterSeconds") == 0
            for index in db.idempotencyRecords.index_information().values()
        )


def test_api_propagates_valid_request_id_and_replaces_invalid_value(
    client
):
    request_id = "mobile-request-123"
    propagated = client.get(
        "/api/health",
        headers={"X-Request-ID": request_id},
    )
    replaced = client.get(
        "/api/health",
        headers={"X-Request-ID": "invalid request id"},
    )

    assert propagated.headers["X-Request-ID"] == request_id
    assert replaced.headers["X-Request-ID"] != "invalid request id"
    assert len(replaced.headers["X-Request-ID"]) == 32


def test_mobile_config_is_public_and_reports_runtime_policy(app, client):
    app.config.update(
        MOBILE_MIN_SUPPORTED_VERSION_CODE=7,
        MOBILE_LATEST_VERSION_CODE=9,
        MOBILE_MAINTENANCE_MODE=True,
        MOBILE_MAINTENANCE_MESSAGE="Kısa süreli bakım yapılıyor.",
        MOBILE_UPDATE_MESSAGE="Uygulamayı güncelleyin.",
        MOBILE_UPDATE_URL="https://play.google.com/store/apps/details?id=test",
    )

    response = client.get("/api/mobile-config")

    assert response.status_code == 200
    assert response.get_json() == {
        "platform": "android",
        "minSupportedVersionCode": 7,
        "latestVersionCode": 9,
        "maintenanceMode": True,
        "maintenanceMessage": "Kısa süreli bakım yapılıyor.",
        "updateMessage": "Uygulamayı güncelleyin.",
        "updateUrl": "https://play.google.com/store/apps/details?id=test",
        "privacyPolicyUrl": "https://example.com/privacy",
        "videoConsentVersion": "video-processing-v1",
    }
    assert response.headers["Cache-Control"] == "no-store"


def test_video_upload_requires_current_revocable_consent(
    app,
    client,
):
    app.config["REQUIRE_VIDEO_CONSENT"] = True
    user = client.post(
        "/api/users",
        json={"phone": "+905551112245"},
    ).get_json()["user"]
    consent_url = (
        f"/api/users/{user['id']}/consents/video-processing"
    )
    video_url = f"/api/users/{user['id']}/videos"

    initial = client.get(consent_url)
    blocked = client.post(
        video_url,
        data={"video": (BytesIO(b"blocked"), "blocked.mp4")},
        content_type="multipart/form-data",
    )
    rejected = client.put(
        consent_url,
        json={
            "version": "video-processing-v1",
            "accepted": False,
        },
    )
    stale = client.put(
        consent_url,
        json={
            "version": "video-processing-v0",
            "accepted": True,
        },
    )
    accepted = client.put(
        consent_url,
        headers={
            "X-App-Version-Code": "7",
            "X-App-Version-Name": "1.2.3",
        },
        json={
            "version": "video-processing-v1",
            "accepted": True,
        },
    )
    accepted_replay = client.put(
        consent_url,
        json={
            "version": "video-processing-v1",
            "accepted": True,
        },
    )
    uploaded = client.post(
        video_url,
        data={"video": (BytesIO(b"accepted"), "accepted.mp4")},
        content_type="multipart/form-data",
    )
    withdrawn = client.delete(consent_url)
    withdrawn_replay = client.delete(consent_url)
    revoked_lookup = client.get(consent_url)
    blocked_again = client.post(
        video_url,
        data={
            "video": (
                BytesIO(b"blocked after withdrawal"),
                "withdrawn.mp4",
            )
        },
        content_type="multipart/form-data",
    )
    reaccepted = client.put(
        consent_url,
        headers={
            "X-App-Version-Code": "8",
            "X-App-Version-Name": "1.2.4",
        },
        json={
            "version": "video-processing-v1",
            "accepted": True,
        },
    )
    uploaded_again = client.post(
        video_url,
        data={
            "video": (
                BytesIO(b"accepted again"),
                "accepted-again.mp4",
            )
        },
        content_type="multipart/form-data",
    )

    assert initial.status_code == 200
    assert initial.get_json()["consent"]["status"] == "required"
    assert blocked.status_code == 428
    assert rejected.status_code == 400
    assert stale.status_code == 409
    assert accepted.status_code == 200
    accepted_consent = accepted.get_json()["consent"]
    assert accepted_consent["status"] == "accepted"
    assert accepted_consent["acceptedAt"]
    assert accepted_consent["appVersionCode"] == "7"
    assert accepted_consent["appVersionName"] == "1.2.3"
    assert [
        item["event"]
        for item in accepted_replay.get_json()["consent"]["events"]
    ] == ["accepted"]
    assert uploaded.status_code == 201
    assert (
        uploaded.get_json()["video"]["consentVersion"]
        == "video-processing-v1"
    )
    assert withdrawn.status_code == 200
    assert withdrawn.get_json()["consent"]["status"] == "revoked"
    assert withdrawn.get_json()["consent"]["revokedAt"]
    assert revoked_lookup.get_json()["consent"]["status"] == "revoked"
    assert [
        item["event"]
        for item in withdrawn_replay.get_json()["consent"]["events"]
    ] == ["accepted", "revoked"]
    assert blocked_again.status_code == 428
    assert reaccepted.status_code == 200
    reaccepted_consent = reaccepted.get_json()["consent"]
    assert reaccepted_consent["status"] == "accepted"
    assert reaccepted_consent["appVersionCode"] == "8"
    assert [
        item["event"]
        for item in reaccepted_consent["events"]
    ] == ["accepted", "revoked", "accepted"]
    assert uploaded_again.status_code == 201


def test_health_endpoints_separate_process_and_database_readiness(
    app, client
):
    live = client.get("/api/live")
    ready = client.get("/api/ready")

    assert live.status_code == 200
    assert live.get_json() == {"status": "ok"}
    assert ready.status_code == 200
    assert ready.get_json() == {"status": "ok", "mongo": "ok"}
    with app.app_context():
        first_client = get_client()
    with app.app_context():
        second_client = get_client()
    assert first_client is second_client


def test_readiness_and_health_reject_missing_ffprobe(app, client):
    app.config.update(
        VIDEO_VALIDATE_CONTENT=True,
        FFPROBE_PATH="/definitely/missing/ffprobe",
    )

    unavailable_ready = client.get("/api/ready")
    unavailable_health = client.get("/api/health")

    assert unavailable_ready.status_code == 503
    assert unavailable_ready.get_json() == {
        "status": "degraded",
        "mongo": "ok",
        "ffprobe": "unavailable",
    }
    assert unavailable_health.status_code == 503
    assert unavailable_health.get_json()["runtimeDependencies"] == {
        "ffprobe": "unavailable"
    }

    app.config["FFPROBE_PATH"] = sys.executable
    recovered_ready = client.get("/api/ready")
    recovered_health = client.get("/api/health")

    assert recovered_ready.status_code == 200
    assert recovered_health.status_code == 200
    assert recovered_health.get_json()["runtimeDependencies"] == {
        "ffprobe": "ok"
    }


def test_video_worker_warms_model_before_publishing_heartbeat(
    app,
    monkeypatch,
):
    app.config.update(
        VIDEO_PROCESSING_MODE="worker",
        TRANSCRIPTION_PROVIDER="faster_whisper",
        FASTER_WHISPER_MODEL_SIZE="tiny",
        VIDEO_WORKER_WARMUP_MODEL=True,
    )
    calls = []
    monkeypatch.setattr(
        "app.services.video_processing.warm_up_transcription_provider",
        lambda: calls.append("warmed"),
    )

    with app.app_context():
        runtime_info = prepare_video_worker_runtime(app.config)

    assert calls == ["warmed"]
    assert runtime_info == {
        "transcriptionProvider": "faster_whisper",
        "transcriptionModel": "tiny",
        "modelWarmed": True,
    }

    monkeypatch.setattr(
        "app.services.video_processing.prepare_video_worker_runtime",
        lambda _config: (_ for _ in ()).throw(
            RuntimeError("model unavailable")
        ),
    )
    stop_event = Event()
    stop_event.set()
    with pytest.raises(RuntimeError, match="model unavailable"):
        run_video_worker(app, stop_event)
    with app.app_context():
        assert get_db().videoWorkerHeartbeats.count_documents({}) == 0


def test_push_worker_validates_fcm_credentials_before_heartbeat(
    app,
    monkeypatch,
):
    app.config.update(
        PUSH_PROVIDER="fcm",
        FCM_PROJECT_ID="test-firebase-project",
        PUSH_WORKER_VALIDATE_CREDENTIALS=True,
    )
    calls = []

    class FakeCredentials:
        def refresh(self, request):
            calls.append(("refresh", request))

    credentials = FakeCredentials()
    firebase_app = object()
    monkeypatch.setattr(
        "app.services.push_notifications.firebase_admin.get_app",
        lambda _name: (_ for _ in ()).throw(ValueError()),
    )
    monkeypatch.setattr(
        "app.services.push_notifications.google.auth.default",
        lambda: (credentials, "test-firebase-project"),
    )
    monkeypatch.setattr(
        "app.services.push_notifications.with_scopes_if_required",
        lambda supplied, scopes: (
            calls.append(("scopes", scopes)) or supplied
        ),
    )
    auth_request = object()
    monkeypatch.setattr(
        "app.services.push_notifications.GoogleAuthRequest",
        lambda: auth_request,
    )
    monkeypatch.setattr(
        "app.services.push_notifications.firebase_admin.initialize_app",
        lambda **_kwargs: firebase_app,
    )

    runtime_info = prepare_push_worker_runtime(app.config)

    assert runtime_info == {
        "provider": "fcm",
        "projectId": "test-firebase-project",
        "credentialsValidated": True,
    }
    assert calls == [
        (
            "scopes",
            [
                "https://www.googleapis.com/auth/"
                "firebase.messaging"
            ],
        ),
        ("refresh", auth_request),
    ]

    monkeypatch.setattr(
        "app.services.push_notifications.prepare_push_worker_runtime",
        lambda _config: (_ for _ in ()).throw(
            RuntimeError("credential refresh failed")
        ),
    )
    stop_event = Event()
    stop_event.set()
    with pytest.raises(
        RuntimeError,
        match="credential refresh failed",
    ):
        run_push_worker(app, stop_event)
    with app.app_context():
        assert get_db().pushWorkerHeartbeats.count_documents({}) == 0


def test_health_requires_worker_startup_validation_metadata(
    app,
    client,
):
    app.config.update(
        VIDEO_PROCESSING_MODE="worker",
        TRANSCRIPTION_PROVIDER="faster_whisper",
        VIDEO_WORKER_WARMUP_MODEL=True,
        PUSH_PROVIDER="fcm",
        FCM_PROJECT_ID="test-firebase-project",
        PUSH_WORKER_VALIDATE_CREDENTIALS=True,
    )
    now = datetime.now(UTC)
    with app.app_context():
        db = get_db()
        db.videoWorkerHeartbeats.insert_one(
            {
                "_id": "legacy-video-worker",
                "status": "running",
                "expiresAt": now + timedelta(minutes=1),
                "updatedAt": now,
            }
        )
        db.pushWorkerHeartbeats.insert_one(
            {
                "_id": "legacy-push-worker",
                "status": "running",
                "expiresAt": now + timedelta(minutes=1),
                "updatedAt": now,
            }
        )

    unvalidated = client.get("/api/health")

    assert unvalidated.status_code == 503
    assert unvalidated.get_json()["videoProcessing"][
        "activeWorkers"
    ] == 1
    assert unvalidated.get_json()["videoProcessing"][
        "readyWorkers"
    ] == 0
    assert unvalidated.get_json()["pushNotifications"][
        "activeWorkers"
    ] == 1
    assert unvalidated.get_json()["pushNotifications"][
        "readyWorkers"
    ] == 0

    with app.app_context():
        db = get_db()
        db.videoWorkerHeartbeats.update_one(
            {"_id": "legacy-video-worker"},
            {
                "$set": {
                    "transcriptionProvider": "faster_whisper",
                    "transcriptionModel": "tiny",
                    "modelWarmed": True,
                }
            },
        )
        db.pushWorkerHeartbeats.update_one(
            {"_id": "legacy-push-worker"},
            {
                "$set": {
                    "provider": "fcm",
                    "projectId": "test-firebase-project",
                    "credentialsValidated": True,
                }
            },
        )

    validated = client.get("/api/health")

    assert validated.status_code == 200
    assert validated.get_json()["videoProcessing"][
        "readyWorkers"
    ] == 1
    assert validated.get_json()["pushNotifications"][
        "readyWorkers"
    ] == 1


def test_production_preflight_checks_runtime_dependencies(
    app,
    tmp_path,
):
    app.config.update(
        APP_ENV="production",
        STRICT_DATA_HYGIENE=True,
        UPLOAD_FOLDER=str(tmp_path / "preflight-uploads"),
        VIDEO_VALIDATE_CONTENT=True,
        FFPROBE_PATH="/usr/bin/true",
        TRANSCRIPTION_PROVIDER="static",
        VIDEO_WORKER_WARMUP_MODEL=False,
        PUSH_PROVIDER="static",
        PUSH_WORKER_VALIDATE_CREDENTIALS=False,
    )

    result = run_production_preflight(app)

    assert result == {
        "status": "ok",
        "checks": {
            "configuration": "ok",
            "mongo": "ok",
            "indexes": "ok",
            "dataHygiene": {
                "status": "ok",
                "invalidPhoneUsers": 0,
            },
            "uploadFolder": "writable",
            "ffprobe": "ok",
        },
        "workers": {
            "video": {
                "transcriptionProvider": "static",
                "transcriptionModel": None,
                "modelWarmed": False,
            },
            "push": {
                "provider": "static",
                "projectId": None,
                "credentialsValidated": False,
            },
        },
    }
    assert list((tmp_path / "preflight-uploads").iterdir()) == []


def test_production_preflight_fails_before_worker_warmup(
    app,
    tmp_path,
    monkeypatch,
):
    app.config.update(
        APP_ENV="production",
        STRICT_DATA_HYGIENE=True,
        UPLOAD_FOLDER=str(tmp_path / "preflight-uploads"),
        VIDEO_VALIDATE_CONTENT=True,
        FFPROBE_PATH="/missing/ffprobe",
    )
    calls = []
    monkeypatch.setattr(
        "app.services.production_preflight.prepare_video_worker_runtime",
        lambda _config: calls.append("video"),
    )
    monkeypatch.setattr(
        "app.services.production_preflight.prepare_push_worker_runtime",
        lambda _config: calls.append("push"),
    )

    with pytest.raises(
        RuntimeError,
        match="could not execute FFPROBE_PATH",
    ):
        run_production_preflight(app)

    assert calls == []


def test_index_initialization_backfills_safe_legacy_phone_and_reports_invalid(
    app, client
):
    legacy_job_time = datetime.now(UTC)
    legacy_deletion_time = legacy_job_time - timedelta(days=1)
    with app.app_context():
        db = get_db()
        safe_legacy_id = db.users.insert_one(
            {
                "name": "Legacy Worker",
                "phone": "5324121036",
                "employerKey": "default",
                "profileStatus": "registered",
                "videoStatus": "not_uploaded",
                "createdAt": datetime.now(UTC),
            }
        ).inserted_id
        db.users.insert_one(
            {
                "name": "Invalid Worker",
                "phone": "+90555923017",
                "employerKey": "default",
                "profileStatus": "registered",
                "videoStatus": "not_uploaded",
                "createdAt": datetime.now(UTC),
            }
        )
        legacy_job_id = db.videoProcessingJobs.insert_one(
            {
                "videoId": ObjectId(),
                "userId": ObjectId(),
                "status": "completed",
                "completedAt": legacy_job_time,
                "createdAt": legacy_job_time,
                "updatedAt": legacy_job_time,
            }
        ).inserted_id
        legacy_deletion_id = db.accountDeletionRecords.insert_one(
            {
                "_id": ObjectId(),
                "status": "completed",
                "requestedAt": legacy_deletion_time,
                "completedAt": legacy_deletion_time,
                "updatedAt": legacy_deletion_time,
            }
        ).inserted_id

    health = client.get("/api/health")

    assert health.status_code == 200
    assert health.get_json()["dataHygiene"] == {
        "invalidPhoneUsers": 1
    }
    with app.app_context():
        migrated = get_db().users.find_one(
            {"_id": safe_legacy_id}
        )
        assert migrated["phone"] == "+905324121036"
        legacy_job = get_db().videoProcessingJobs.find_one(
            {"_id": legacy_job_id}
        )
        assert (
            legacy_job["purgeAt"] - legacy_job["completedAt"]
            == timedelta(
                seconds=TestConfig.VIDEO_JOB_RETENTION_SECONDS
            )
        )
        purge_index = get_db().videoProcessingJobs.index_information()
        assert any(
            item.get("expireAfterSeconds") == 0
            and item.get("key") == [("purgeAt", 1)]
            for item in purge_index.values()
        )
        legacy_deletion = get_db().accountDeletionRecords.find_one(
            {"_id": legacy_deletion_id}
        )
        assert (
            legacy_deletion["purgeAt"]
            - legacy_deletion["completedAt"]
        ) == timedelta(
            days=TestConfig.ACCOUNT_DELETION_AUDIT_RETENTION_DAYS
        )
        deletion_indexes = (
            get_db().accountDeletionRecords.index_information()
        )
        assert any(
            item.get("expireAfterSeconds") == 0
            and item.get("key") == [("purgeAt", 1)]
            for item in deletion_indexes.values()
        )

    app.config["STRICT_DATA_HYGIENE"] = True
    strict_health = client.get("/api/health")

    assert strict_health.status_code == 503
    assert strict_health.get_json()["status"] == "degraded"
    assert strict_health.get_json()["dataHygiene"] == {
        "invalidPhoneUsers": 1
    }


def test_health_reports_stale_idempotency_processing_as_degraded(
    app, client
):
    with app.app_context():
        now = datetime.now(UTC)
        get_db().idempotencyRecords.insert_one(
            {
                "scope": "worker:POST:test.action",
                "idempotencyKey": "stale-request-0001",
                "requestHash": "test-hash",
                "status": "processing",
                "ownerId": "dead-request",
                "createdAt": now - timedelta(minutes=5),
                "updatedAt": now - timedelta(minutes=5),
                "expiresAt": now - timedelta(seconds=1),
            }
        )

    health = client.get("/api/health")

    assert health.status_code == 503
    assert health.get_json()["status"] == "degraded"
    assert health.get_json()["idempotency"] == {
        "processing": 1,
        "staleProcessing": 1,
    }

def test_json_body_limit_rejects_oversized_request(app, client):
    app.config["MAX_JSON_CONTENT_LENGTH"] = 64

    response = client.post(
        "/api/users",
        json={
            "phone": "+905551112244",
            "padding": "x" * 128,
        },
        headers={"X-Request-ID": "oversized-json-1"},
    )

    assert response.status_code == 413
    assert response.get_json()["requestId"] == "oversized-json-1"
    assert response.headers["X-Request-ID"] == "oversized-json-1"


def test_upload_video_updates_dashboard(app, client):
    user_response = client.post("/api/users", json={"phone": "+905554445566"})
    user_id = user_response.get_json()["user"]["id"]

    upload = client.post(
        f"/api/users/{user_id}/videos",
        data={"video": (BytesIO(b"fake mp4 content"), "intro.mp4")},
        content_type="multipart/form-data",
    )

    assert upload.status_code == 201
    video = upload.get_json()["video"]
    assert video["status"] == "completed"

    dashboard = client.get(f"/api/users/{user_id}/dashboard").get_json()
    assert dashboard["user"]["name"] == "Mehmet Yılmaz"
    assert dashboard["user"]["nameStatus"] == "inferred_from_video"
    assert dashboard["user"]["profileReviewStatus"] == "pending"
    assert dashboard["user"]["profileStatus"] == "profile_ready"
    assert dashboard["user"]["videoStatus"] == "completed"
    assert dashboard["latestVideo"]["id"] == video["id"]
    assert dashboard["latestVideo"]["status"] == "completed"
    assert dashboard["latestVideo"]["sourceDeletionStatus"] == "deleted"
    assert dashboard["latestVideo"]["sourceDeletedAt"] is not None
    assert dashboard["latestTranscript"]["status"] == "completed"
    assert "Adım Mehmet Yılmaz" in dashboard["latestTranscript"]["text"]
    assert dashboard["candidateProfile"]["latestVideoId"] == video["id"]
    assert dashboard["candidateProfile"]["name"] == "Mehmet Yılmaz"
    assert "kaynak" in dashboard["candidateProfile"]["skills"]
    assert "araç kullanma" in dashboard["candidateProfile"]["skills"]
    assert "vardiya uyumu" in dashboard["candidateProfile"]["skills"]
    assert len(dashboard["recommendedJobs"]) == 3
    assert dashboard["recommendedJobs"][0]["matchScore"] >= dashboard["recommendedJobs"][1]["matchScore"]
    assert dashboard["recommendedJobs"][0]["applicationStatus"] == "not_applied"
    with app.app_context():
        db = get_db()
        stored_video = db.videos.find_one(
            {"_id": ObjectId(video["id"])}
        )
        assert "storedPath" not in stored_video
        completed_job = db.videoProcessingJobs.find_one(
            {"videoId": ObjectId(video["id"])}
        )
        assert (
            completed_job["purgeAt"]
            - completed_job["completedAt"]
            == timedelta(
                seconds=TestConfig.VIDEO_JOB_RETENTION_SECONDS
            )
        )
    assert list(
        (Path(TestConfig.UPLOAD_FOLDER) / user_id).glob("*")
    ) == []


def test_worker_reviews_profile_name_and_future_video_preserves_it(
    app,
    client,
):
    user = client.post(
        "/api/users", json={"phone": "+905554445567"}
    ).get_json()["user"]
    review_url = f"/api/users/{user['id']}/profile-review"

    too_early = client.put(
        review_url,
        json={"name": "Mehmet Yılmaz"},
    )
    upload = client.post(
        f"/api/users/{user['id']}/videos",
        data={"video": (BytesIO(b"profile review"), "profile.mp4")},
        content_type="multipart/form-data",
    )
    invalid_name = client.put(
        review_url,
        json={"name": "Mehmet 123"},
    )
    unknown_field = client.put(
        review_url,
        json={"name": "Mehmet Yılmaz", "skills": []},
    )
    confirmed = client.put(
        review_url,
        json={"name": "  Mehmet   Yılmaz  "},
    )

    dashboard = client.get(
        f"/api/users/{user['id']}/dashboard"
    ).get_json()
    recommendation = dashboard["recommendedJobs"][0]
    application = client.post(
        f"/api/users/{user['id']}/job-applications",
        json={"jobRecommendationId": recommendation["id"]},
    ).get_json()["jobApplication"]
    corrected = client.put(
        review_url,
        json={"name": "Mehmet Yalçın"},
    )
    replayed = client.put(
        review_url,
        json={"name": "Mehmet Yalçın"},
    )

    app.config["TRANSCRIPTION_STATIC_TEXT"] = (
        "Adım Başka Kişi. Kaynak işlerinde deneyimliyim ve "
        "vardiyalı çalışabilirim."
    )
    second_upload = client.post(
        f"/api/users/{user['id']}/videos",
        data={
            "video": (
                BytesIO(b"updated profile review"),
                "profile-update.mp4",
            )
        },
        content_type="multipart/form-data",
    )
    final_dashboard = client.get(
        f"/api/users/{user['id']}/dashboard"
    ).get_json()

    assert too_early.status_code == 409
    assert upload.status_code == 201
    assert invalid_name.status_code == 400
    assert unknown_field.status_code == 400
    assert confirmed.status_code == 200
    confirmed_payload = confirmed.get_json()
    assert confirmed_payload["user"]["name"] == "Mehmet Yılmaz"
    assert (
        confirmed_payload["user"]["nameStatus"]
        == "confirmed_by_worker"
    )
    assert (
        confirmed_payload["user"]["profileReviewStatus"]
        == "confirmed"
    )
    assert confirmed_payload["user"]["profileReviewedAt"]
    assert (
        confirmed_payload["candidateProfile"]["nameSource"]
        == "worker_review"
    )
    assert corrected.status_code == 200
    assert (
        corrected.get_json()["user"]["nameStatus"]
        == "corrected_by_worker"
    )
    assert (
        replayed.get_json()["user"]["nameStatus"]
        == "corrected_by_worker"
    )
    assert second_upload.status_code == 201
    assert final_dashboard["user"]["name"] == "Mehmet Yalçın"
    assert (
        final_dashboard["user"]["nameStatus"]
        == "corrected_by_worker"
    )
    assert (
        final_dashboard["user"]["profileReviewStatus"]
        == "confirmed"
    )
    assert (
        final_dashboard["candidateProfile"]["name"]
        == "Mehmet Yalçın"
    )
    assert (
        final_dashboard["candidateProfile"]["nameSource"]
        == "worker_review"
    )
    with app.app_context():
        stored_application = get_db().jobApplications.find_one(
            {"_id": ObjectId(application["id"])}
        )
        assert stored_application["candidate"]["name"] == (
            "Mehmet Yalçın"
        )
        assert stored_application["candidateUpdatedAt"]


def test_worker_data_export_contains_public_personal_data_only(
    app,
    client,
):
    user = client.post(
        "/api/users", json={"phone": "+905554445588"}
    ).get_json()["user"]
    consent = client.put(
        f"/api/users/{user['id']}/consents/video-processing",
        headers={
            "X-App-Version-Code": "1",
            "X-App-Version-Name": "1.0",
        },
        json={
            "version": "video-processing-v1",
            "accepted": True,
        },
    )
    upload = client.post(
        f"/api/users/{user['id']}/videos",
        data={"video": (BytesIO(b"export video"), "export.mp4")},
        content_type="multipart/form-data",
    )
    client.post(
        f"/api/users/{user['id']}/questions",
        headers={"Idempotency-Key": "data-export-question-0001"},
        json={"question": "Servis bilgim nedir?"},
    )
    assignment = client.put(
        "/api/employers/default/workers/"
        f"{user['id']}/support-assignments",
        json={
            "assessmentIds": ["safety-readiness"],
            "trainingIds": ["isg-101"],
        },
    )
    device = client.put(
        f"/api/users/{user['id']}/devices/"
        "11111111-1111-4111-8111-111111111111",
        json={
            "fid": "export-device-fid-000000000001",
            "platform": "android",
            "appVersionCode": 1,
            "appVersionName": "1.0",
        },
    )

    response = client.get(
        f"/api/users/{user['id']}/data-export"
    )

    assert upload.status_code == 201
    assert consent.status_code == 200
    assert assignment.status_code == 200
    assert device.status_code == 200
    assert response.status_code == 200
    assert response.headers["Content-Disposition"] == (
        f'attachment; filename="worker-data-{user["id"]}.json"'
    )
    payload = response.get_json()
    assert payload["schemaVersion"] == 2
    assert payload["exportedAt"]
    assert payload["user"]["phone"] == "+905554445588"
    assert payload["consents"][0]["status"] == "accepted"
    assert payload["consents"][0]["version"] == (
        "video-processing-v1"
    )
    assert payload["videos"][0]["originalFilename"] == "export.mp4"
    assert "storedPath" not in payload["videos"][0]
    assert payload["transcripts"][0]["text"]
    assert payload["candidateProfile"]["name"] == "Mehmet Yılmaz"
    assert payload["jobRecommendations"]
    assert (
        payload["workerSupport"]["questions"][0]["question"]
        == "Servis bilgim nedir?"
    )
    assert payload["workerSupport"]["assignments"] == {
        "assessmentIds": ["safety-readiness"],
        "trainingIds": ["isg-101"],
    }
    assert payload["devices"] == [
        {
            "installationId": (
                "11111111-1111-4111-8111-111111111111"
            ),
            "platform": "android",
            "appVersionCode": 1,
            "appVersionName": "1.0",
            "active": True,
            "lastSeenAt": payload["devices"][0]["lastSeenAt"],
        }
    ]
    serialized = response.get_data(as_text=True)
    assert "codeHash" not in serialized
    assert "tokenHash" not in serialized
    assert "fidHash" not in serialized
    assert "lockToken" not in serialized


def test_worker_account_deletion_removes_support_assignments(
    app,
    client,
):
    user = client.post(
        "/api/users",
        json={"phone": "+905554445589"},
    ).get_json()["user"]
    assignment = client.put(
        "/api/employers/default/workers/"
        f"{user['id']}/support-assignments",
        json={
            "assessmentIds": ["safety-readiness"],
            "trainingIds": [],
        },
    )
    installation_id = "22222222-2222-4222-8222-222222222222"
    device = client.put(
        f"/api/users/{user['id']}/devices/{installation_id}",
        json={
            "fid": "deletion-device-fid-0000000001",
            "platform": "android",
            "appVersionCode": 1,
            "appVersionName": "1.0",
        },
    )
    with app.app_context():
        enqueue_worker_push(
            get_db(),
            user_id=ObjectId(user["id"]),
            event_key="delete-account-event",
            event_type="question_answered",
            title="Test",
            body="Test bildirimi",
            data={"entityId": str(ObjectId())},
        )

    deleted = client.delete(f"/api/users/{user['id']}")

    assert assignment.status_code == 200
    assert device.status_code == 200
    assert deleted.status_code == 204
    with app.app_context():
        assert get_db().workerSupportAssignments.count_documents(
            {"userId": ObjectId(user["id"])}
        ) == 0
        assert get_db().workerPushRegistrations.count_documents(
            {"userId": ObjectId(user["id"])}
        ) == 0
        assert get_db().pushNotificationJobs.count_documents(
            {"userId": ObjectId(user["id"])}
        ) == 0


def test_video_upload_idempotency_validates_digest_and_replays(
    app, client
):
    app.config.update(
        REQUIRE_IDEMPOTENCY_KEY=True,
        VIDEO_PROCESSING_INLINE=False,
        VIDEO_PROCESSING_MODE="worker",
    )
    user = client.post(
        "/api/users", json={"phone": "+905554445577"}
    ).get_json()["user"]
    path = f"/api/users/{user['id']}/videos"
    content = b"idempotent video content"
    digest = hashlib.sha256(content).hexdigest()
    headers = {
        "Idempotency-Key": "video-upload-request-0001",
        "X-Upload-SHA256": digest,
    }

    first = client.post(
        path,
        headers=headers,
        data={"video": (BytesIO(content), "intro.mp4")},
        content_type="multipart/form-data",
    )
    replay = client.post(
        path,
        headers=headers,
        data={"video": (BytesIO(content), "intro.mp4")},
        content_type="multipart/form-data",
    )
    conflicting = client.post(
        path,
        headers={
            **headers,
            "X-Upload-SHA256": hashlib.sha256(
                b"different video"
            ).hexdigest(),
        },
        data={"video": (BytesIO(b"different video"), "other.mp4")},
        content_type="multipart/form-data",
    )
    missing_digest = client.post(
        path,
        headers={"Idempotency-Key": "video-upload-request-0002"},
        data={"video": (BytesIO(content), "intro.mp4")},
        content_type="multipart/form-data",
    )
    mismatched_digest = client.post(
        path,
        headers={
            "Idempotency-Key": "video-upload-request-0003",
            "X-Upload-SHA256": hashlib.sha256(
                b"not the uploaded content"
            ).hexdigest(),
        },
        data={"video": (BytesIO(content), "intro.mp4")},
        content_type="multipart/form-data",
    )
    missing_key = client.post(
        path,
        headers={"X-Upload-SHA256": digest},
        data={"video": (BytesIO(content), "intro.mp4")},
        content_type="multipart/form-data",
    )

    assert first.status_code == 201
    assert first.headers["Idempotency-Replayed"] == "false"
    assert replay.status_code == 201
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert replay.get_json() == first.get_json()
    assert conflicting.status_code == 409
    assert missing_digest.status_code == 400
    assert mismatched_digest.status_code == 400
    assert missing_key.status_code == 400

    with app.app_context():
        db = get_db()
        assert db.videos.count_documents(
            {"userId": ObjectId(user["id"])}
        ) == 1
        assert db.videoProcessingJobs.count_documents(
            {"userId": ObjectId(user["id"])}
        ) == 1
        record = db.idempotencyRecords.find_one(
            {"idempotencyKey": headers["Idempotency-Key"]}
        )
        assert record["status"] == "completed"
        assert db.idempotencyRecords.count_documents(
            {"idempotencyKey": "video-upload-request-0003"}
        ) == 0
    assert len(
        list((Path(TestConfig.UPLOAD_FOLDER) / user["id"]).glob("*"))
    ) == 1


def test_completed_video_source_deletion_failure_is_retried(
    app, client, monkeypatch
):
    app.config.update(
        VIDEO_PROCESSING_INLINE=False,
        VIDEO_PROCESSING_MODE="worker",
    )
    user = client.post(
        "/api/users", json={"phone": "+905550006603"}
    ).get_json()["user"]
    upload = client.post(
        f"/api/users/{user['id']}/videos",
        data={"video": (BytesIO(b"retention video"), "retention.mp4")},
        content_type="multipart/form-data",
    ).get_json()["video"]

    monkeypatch.setattr(
        "app.services.video_processing._remove_video_source_file",
        lambda _path: (_ for _ in ()).throw(
            PermissionError("storage is read-only")
        ),
    )
    with app.app_context():
        db = get_db()
        job = claim_video_job(
            db,
            app.config,
            video_id=ObjectId(upload["id"]),
            worker_id="retention-worker",
        )
        process_claimed_video_job(job)
        failed_deletion = db.videos.find_one(
            {"_id": ObjectId(upload["id"])}
        )
        completed_job = db.videoProcessingJobs.find_one(
            {"videoId": ObjectId(upload["id"])}
        )

        assert completed_job["status"] == "completed"
        assert failed_deletion["status"] == "completed"
        assert failed_deletion["sourceDeletionStatus"] == "failed"
        assert Path(failed_deletion["storedPath"]).is_file()

        monkeypatch.setattr(
            "app.services.video_processing._remove_video_source_file",
            lambda path: path.unlink(missing_ok=True),
        )
        assert cleanup_pending_video_sources(db) == 1
        deleted_source = db.videos.find_one(
            {"_id": ObjectId(upload["id"])}
        )
        assert deleted_source["sourceDeletionStatus"] == "deleted"
        assert deleted_source["sourceDeletionAttempts"] == 2
        assert "storedPath" not in deleted_source


def test_video_uploads_are_rate_limited_per_worker(app, client):
    app.config.update(
        VIDEO_UPLOAD_RATE_LIMIT_WINDOW_SECONDS=60,
        VIDEO_UPLOAD_MAX_REQUESTS=1,
    )
    user = client.post(
        "/api/users", json={"phone": "+905550006604"}
    ).get_json()["user"]

    first = client.post(
        f"/api/users/{user['id']}/videos",
        data={"video": (BytesIO(b"first video"), "first.mp4")},
        content_type="multipart/form-data",
    )
    limited = client.post(
        f"/api/users/{user['id']}/videos",
        data={"video": (BytesIO(b"second video"), "second.mp4")},
        content_type="multipart/form-data",
    )

    assert first.status_code == 201
    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) > 0
    with app.app_context():
        db = get_db()
        assert db.videos.count_documents(
            {"userId": ObjectId(user["id"])}
        ) == 1
        assert db.videoProcessingJobs.count_documents(
            {"userId": ObjectId(user["id"])}
        ) == 1


def test_older_video_completion_cannot_replace_latest_profile(
    app, client, monkeypatch
):
    app.config.update(
        VIDEO_PROCESSING_INLINE=False,
        VIDEO_PROCESSING_MODE="worker",
    )
    user = client.post(
        "/api/users", json={"phone": "+905550006601"}
    ).get_json()["user"]
    older = client.post(
        f"/api/users/{user['id']}/videos",
        data={"video": (BytesIO(b"older"), "older.mp4")},
        content_type="multipart/form-data",
    ).get_json()["video"]
    latest = client.post(
        f"/api/users/{user['id']}/videos",
        data={"video": (BytesIO(b"latest"), "latest.mp4")},
        content_type="multipart/form-data",
    ).get_json()["video"]

    def fake_transcription(video):
        candidate = (
            "Eski Kullanıcı"
            if video["originalFilename"] == "older.mp4"
            else "Yeni Kullanıcı"
        )
        return {
            "provider": "static",
            "status": "completed",
            "text": f"Adım {candidate}. Kaynak işinde deneyimliyim.",
            "segments": [],
            "metadata": {"language": "tr"},
            "warnings": [],
        }

    monkeypatch.setattr(
        "app.services.video_processing.transcribe_video",
        fake_transcription,
    )
    with app.app_context():
        old_job = claim_video_job(
            get_db(),
            app.config,
            video_id=ObjectId(older["id"]),
            worker_id="old-worker",
        )
        process_claimed_video_job(old_job)

    while_latest_is_pending = client.get(
        f"/api/users/{user['id']}/dashboard"
    ).get_json()
    assert while_latest_is_pending["latestVideo"]["id"] == latest["id"]
    assert while_latest_is_pending["user"]["videoStatus"] == "processing"
    assert while_latest_is_pending["candidateProfile"] is None
    assert while_latest_is_pending["recommendedJobs"] == []

    with app.app_context():
        latest_job = claim_video_job(
            get_db(),
            app.config,
            video_id=ObjectId(latest["id"]),
            worker_id="latest-worker",
        )
        process_claimed_video_job(latest_job)

    completed = client.get(
        f"/api/users/{user['id']}/dashboard"
    ).get_json()
    assert completed["user"]["name"] == "Yeni Kullanıcı"
    assert completed["candidateProfile"]["latestVideoId"] == latest["id"]
    assert completed["candidateProfile"]["name"] == "Yeni Kullanıcı"
    assert all(
        item["videoId"] == latest["id"]
        for item in completed["recommendedJobs"]
    )


def test_older_video_failure_cannot_mark_latest_video_failed(
    app, client, monkeypatch
):
    app.config.update(
        VIDEO_PROCESSING_INLINE=False,
        VIDEO_PROCESSING_MODE="worker",
        VIDEO_JOB_MAX_ATTEMPTS=1,
    )
    user = client.post(
        "/api/users", json={"phone": "+905550006602"}
    ).get_json()["user"]
    older = client.post(
        f"/api/users/{user['id']}/videos",
        data={"video": (BytesIO(b"older"), "older.mp4")},
        content_type="multipart/form-data",
    ).get_json()["video"]
    latest = client.post(
        f"/api/users/{user['id']}/videos",
        data={"video": (BytesIO(b"latest"), "latest.mp4")},
        content_type="multipart/form-data",
    ).get_json()["video"]
    monkeypatch.setattr(
        "app.services.video_processing.transcribe_video",
        lambda _video: (_ for _ in ()).throw(
            RuntimeError("permanent transcription failure")
        ),
    )

    with app.app_context():
        old_job = claim_video_job(
            get_db(),
            app.config,
            video_id=ObjectId(older["id"]),
            worker_id="failing-worker",
        )
        process_claimed_video_job(old_job)
        stored_user = get_db().users.find_one(
            {"_id": ObjectId(user["id"])}
        )
        stored_old_video = get_db().videos.find_one(
            {"_id": ObjectId(older["id"])}
        )

    assert stored_old_video["status"] == "failed"
    assert str(stored_user["latestVideoId"]) == latest["id"]
    assert stored_user["videoStatus"] == "processing"
    assert stored_user["profileStatus"] == "video_processing"


def test_upload_rejects_file_without_video_stream(app, client):
    app.config["VIDEO_VALIDATE_CONTENT"] = True
    user = client.post(
        "/api/users", json={"phone": "+905550006677"}
    ).get_json()["user"]

    upload = client.post(
        f"/api/users/{user['id']}/videos",
        data={"video": (BytesIO(b"not a video"), "invalid.mp4")},
        content_type="multipart/form-data",
    )
    dashboard = client.get(
        f"/api/users/{user['id']}/dashboard"
    ).get_json()

    assert upload.status_code == 400
    assert dashboard["user"]["videoStatus"] == "not_uploaded"
    assert dashboard["latestVideo"] is None


def test_upload_cleans_up_file_and_documents_when_job_creation_fails(
    app, client, monkeypatch
):
    user = client.post(
        "/api/users", json={"phone": "+905550006678"}
    ).get_json()["user"]
    monkeypatch.setattr(
        "app.routes.videos.create_processing_job",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("queue unavailable")
        ),
    )

    upload = client.post(
        f"/api/users/{user['id']}/videos",
        data={"video": (BytesIO(b"video"), "orphan.mp4")},
        content_type="multipart/form-data",
    )

    assert upload.status_code == 500
    with app.app_context():
        db = get_db()
        assert db.videos.count_documents(
            {"userId": ObjectId(user["id"])}
        ) == 0
        assert db.videoProcessingJobs.count_documents(
            {"userId": ObjectId(user["id"])}
        ) == 0
        stored_user = db.users.find_one({"_id": ObjectId(user["id"])})
        assert stored_user["videoStatus"] == "not_uploaded"
        assert stored_user["latestVideoId"] is None

    user_upload_dir = Path(TestConfig.UPLOAD_FOLDER) / user["id"]
    assert list(user_upload_dir.glob("*")) == []


def test_dashboard_does_not_publish_template_jobs_when_fallback_is_disabled(
    app, client
):
    app.config["JOB_RECOMMENDATION_FALLBACK_ENABLED"] = False
    user = client.post(
        "/api/users", json={"phone": "+905550006688"}
    ).get_json()["user"]

    client.post(
        f"/api/users/{user['id']}/videos",
        data={"video": (BytesIO(b"video"), "profile.mp4")},
        content_type="multipart/form-data",
    )
    dashboard = client.get(
        f"/api/users/{user['id']}/dashboard"
    ).get_json()

    assert dashboard["user"]["profileStatus"] == "profile_ready"
    assert dashboard["recommendedJobs"] == []


def test_video_processing_job_retries_and_completes(
    app, client, monkeypatch
):
    app.config.update(
        VIDEO_PROCESSING_INLINE=False,
        VIDEO_PROCESSING_MODE="worker",
        VIDEO_JOB_MAX_ATTEMPTS=3,
        VIDEO_JOB_LEASE_SECONDS=60,
        VIDEO_JOB_HEARTBEAT_SECONDS=10,
        VIDEO_JOB_RETRY_BASE_SECONDS=0,
        VIDEO_JOB_RETRY_MAX_SECONDS=0,
    )
    user_response = client.post(
        "/api/users", json={"phone": "+905550001122"}
    )
    user_id = user_response.get_json()["user"]["id"]
    upload = client.post(
        f"/api/users/{user_id}/videos",
        data={"video": (BytesIO(b"retry video"), "retry.mp4")},
        content_type="multipart/form-data",
    )
    video_id = upload.get_json()["video"]["id"]

    with app.app_context():
        db = get_db()
        queued = db.videoProcessingJobs.find_one(
            {"videoId": ObjectId(video_id)}
        )
        assert queued["status"] == "queued"
        assert queued["attempts"] == 0

        first_claim = claim_video_job(
            db, app.config, video_id=ObjectId(video_id), worker_id="worker-1"
        )
        monkeypatch.setattr(
            "app.services.video_processing.transcribe_video",
            lambda _video: (_ for _ in ()).throw(
                RuntimeError("temporary transcription outage")
            ),
        )
        process_claimed_video_job(first_claim)

        retry_job = db.videoProcessingJobs.find_one({"_id": queued["_id"]})
        assert retry_job["status"] == "queued"
        assert retry_job["attempts"] == 1
        assert retry_job["lastError"] == "temporary transcription outage"
        assert retry_job["availableAt"] <= datetime.now(UTC)

        second_claim = claim_video_job(
            db, app.config, video_id=ObjectId(video_id), worker_id="worker-2"
        )
        monkeypatch.setattr(
            "app.services.video_processing.transcribe_video",
            lambda _video: {
                "provider": "static",
                "status": "completed",
                "text": "Adım Ayşe Demir. Kaynak işlerinde deneyimliyim.",
                "segments": [],
                "metadata": {"language": "tr"},
                "warnings": [],
            },
        )
        process_claimed_video_job(second_claim)

        completed = db.videoProcessingJobs.find_one({"_id": queued["_id"]})
        video = db.videos.find_one({"_id": ObjectId(video_id)})
        assert completed["status"] == "completed"
        assert completed["attempts"] == 2
        assert "lockToken" not in completed
        assert video["status"] == "completed"
        assert db.candidateProfiles.find_one(
            {"userId": ObjectId(user_id)}
        )["name"] == "Ayşe Demir"
        assert db.jobRecommendations.count_documents(
            {"videoId": ObjectId(video_id)}
        ) == 3


def test_terminal_video_job_has_retention_and_degrades_health(
    app,
    client,
    monkeypatch,
):
    app.config.update(
        VIDEO_PROCESSING_INLINE=False,
        VIDEO_PROCESSING_MODE="worker",
        VIDEO_JOB_MAX_ATTEMPTS=1,
    )
    user = client.post(
        "/api/users",
        json={"phone": "+905550001123"},
    ).get_json()["user"]
    upload = client.post(
        f"/api/users/{user['id']}/videos",
        data={
            "video": (
                BytesIO(b"terminal failure"),
                "terminal.mp4",
            )
        },
        content_type="multipart/form-data",
    ).get_json()["video"]

    with app.app_context():
        db = get_db()
        job = claim_video_job(
            db,
            app.config,
            video_id=ObjectId(upload["id"]),
            worker_id="terminal-worker",
        )
        monkeypatch.setattr(
            "app.services.video_processing.transcribe_video",
            lambda _video: (_ for _ in ()).throw(
                RuntimeError("terminal transcription outage")
            ),
        )
        process_claimed_video_job(job)
        failed = db.videoProcessingJobs.find_one(
            {"_id": job["_id"]}
        )

        assert failed["status"] == "failed"
        assert (
            failed["purgeAt"] - failed["failedAt"]
            == timedelta(
                seconds=TestConfig.VIDEO_JOB_RETENTION_SECONDS
            )
        )

    health = client.get("/api/health")
    assert health.status_code == 503
    assert health.get_json()["status"] == "degraded"
    assert (
        health.get_json()["videoProcessing"]["queue"]["failed"]
        == 1
    )


def test_account_deletion_during_transcription_cancels_worker_writes(
    app,
    client,
    monkeypatch,
):
    app.config.update(
        VIDEO_PROCESSING_INLINE=False,
        VIDEO_PROCESSING_MODE="worker",
    )
    user = client.post(
        "/api/users", json={"phone": "+905550006609"}
    ).get_json()["user"]
    upload = client.post(
        f"/api/users/{user['id']}/videos",
        data={"video": (BytesIO(b"deletion race"), "race.mp4")},
        content_type="multipart/form-data",
    ).get_json()["video"]

    with app.app_context():
        db = get_db()
        job = claim_video_job(
            db,
            app.config,
            video_id=ObjectId(upload["id"]),
            worker_id="deletion-race-worker",
        )

    def delete_during_transcription(_video):
        now = datetime.now(UTC)
        get_db().accountDeletionRecords.insert_one(
            {
                "_id": ObjectId(user["id"]),
                "status": "processing",
                "requestedAt": now,
                "updatedAt": now,
            }
        )
        return {
            "provider": "static",
            "language": "tr",
            "text": "This must not be persisted",
            "segments": [],
            "warnings": [],
        }

    monkeypatch.setattr(
        "app.services.video_processing.transcribe_video",
        delete_during_transcription,
    )
    with app.app_context():
        process_claimed_video_job(job)
        db = get_db()
        assert db.videoProcessingJobs.count_documents(
            {"videoId": ObjectId(upload["id"])}
        ) == 0
        assert db.videoTranscripts.count_documents(
            {"userId": ObjectId(user["id"])}
        ) == 0
        assert db.candidateProfiles.count_documents(
            {"userId": ObjectId(user["id"])}
        ) == 0
        assert db.jobRecommendations.count_documents(
            {"userId": ObjectId(user["id"])}
        ) == 0


def test_stale_video_processing_lease_can_be_reclaimed(app, client):
    app.config.update(
        VIDEO_PROCESSING_INLINE=False,
        VIDEO_PROCESSING_MODE="worker",
        VIDEO_JOB_MAX_ATTEMPTS=3,
        VIDEO_JOB_LEASE_SECONDS=60,
    )
    user = client.post(
        "/api/users", json={"phone": "+905550003344"}
    ).get_json()["user"]
    upload = client.post(
        f"/api/users/{user['id']}/videos",
        data={"video": (BytesIO(b"stale video"), "stale.mp4")},
        content_type="multipart/form-data",
    ).get_json()["video"]

    with app.app_context():
        db = get_db()
        job = db.videoProcessingJobs.find_one(
            {"videoId": ObjectId(upload["id"])}
        )
        db.videoProcessingJobs.update_one(
            {"_id": job["_id"]},
            {
                "$set": {
                    "status": "processing",
                    "attempts": 1,
                    "lockToken": "stale-lock",
                    "lockedBy": "dead-worker",
                    "leaseExpiresAt": datetime.now(UTC)
                    - timedelta(seconds=1),
                }
            },
        )

        reclaimed = claim_video_job(
            db,
            app.config,
            video_id=ObjectId(upload["id"]),
            worker_id="replacement-worker",
        )
        duplicate_claim = claim_video_job(
            db,
            app.config,
            video_id=ObjectId(upload["id"]),
            worker_id="other-worker",
        )

        assert reclaimed is not None
        assert reclaimed["attempts"] == 2
        assert reclaimed["lockedBy"] == "replacement-worker"
        assert reclaimed["lockToken"] != "stale-lock"
        assert duplicate_claim is None

    health = client.get("/api/health").get_json()
    assert health["status"] == "degraded"
    assert health["videoProcessing"]["queue"]["processing"] == 1


def test_transcription_provider_failure_is_retryable(
    app, monkeypatch
):
    app.config["TRANSCRIPTION_PROVIDER"] = "faster_whisper"
    monkeypatch.setattr(
        "app.services.transcription._get_faster_whisper_model",
        lambda: (_ for _ in ()).throw(
            RuntimeError("model unavailable")
        ),
    )

    with app.app_context(), pytest.raises(
        RuntimeError, match="transcription provider failed"
    ):
        transcribe_video(
            {
                "_id": ObjectId(),
                "storedPath": "/tmp/missing-video.mp4",
            }
        )


def test_worker_can_apply_to_recommended_job_and_employer_can_update_status(client):
    user_response = client.post(
        "/api/users",
        json={"phone": "+905554445500", "employerKey": "acme"},
    )
    user_id = user_response.get_json()["user"]["id"]
    client.post(
        f"/api/users/{user_id}/videos",
        data={"video": (BytesIO(b"fake mp4 content"), "intro.mp4")},
        content_type="multipart/form-data",
    )
    dashboard = client.get(f"/api/users/{user_id}/dashboard").get_json()
    recommendation = dashboard["recommendedJobs"][0]

    invalid_cover_note = client.post(
        f"/api/users/{user_id}/job-applications",
        json={
            "jobRecommendationId": recommendation["id"],
            "coverNote": 123,
        },
    )
    apply_response = client.post(
        f"/api/users/{user_id}/job-applications",
        json={"jobRecommendationId": recommendation["id"], "coverNote": "Vardiyalı çalışabilirim."},
    )
    duplicate_response = client.post(
        f"/api/users/{user_id}/job-applications",
        json={"jobRecommendationId": recommendation["id"]},
    )

    assert invalid_cover_note.status_code == 400
    assert apply_response.status_code == 201
    application = apply_response.get_json()["jobApplication"]
    assert application["status"] == "submitted"
    assert application["coverNote"] == "Vardiyalı çalışabilirim."
    assert application["job"]["title"] == recommendation["title"]
    assert application["candidate"]["phone"] == "+905554445500"
    assert duplicate_response.status_code == 200
    assert duplicate_response.get_json()["jobApplication"]["id"] == application["id"]

    updated_dashboard = client.get(f"/api/users/{user_id}/dashboard").get_json()
    applied_job = next(item for item in updated_dashboard["recommendedJobs"] if item["id"] == recommendation["id"])
    assert applied_job["applicationId"] == application["id"]
    assert applied_job["applicationStatus"] == "submitted"
    assert updated_dashboard["jobApplications"][0]["id"] == application["id"]

    employer_payload = client.get(
        "/api/employers/acme/job-applications?limit=1"
    ).get_json()
    employer_list = employer_payload["jobApplications"]
    assert employer_list[0]["id"] == application["id"]
    assert employer_payload["pagination"] == {
        "page": 1,
        "limit": 1,
        "total": 1,
        "pages": 1,
    }
    invalid_page = client.get(
        "/api/employers/acme/job-applications?page=invalid"
    )
    assert invalid_page.status_code == 400

    interview_at = (
        datetime.now(UTC) + timedelta(days=2)
    ).replace(microsecond=0)
    status_update = client.patch(
        f"/api/employers/acme/job-applications/{application['id']}",
        json={
            "status": "shortlisted",
            "note": "Telefon görüşmesine alınacak.",
            "interview": {
                "scheduledAt": interview_at.isoformat(),
                "type": "onsite",
                "location": "ACME Kocaeli Fabrikası",
                "note": "Güvenlik girişinde kimlik gösterin.",
            },
        },
    )
    assert status_update.status_code == 200
    updated_application = status_update.get_json()["jobApplication"]
    assert updated_application["status"] == "shortlisted"
    assert updated_application["interview"] == {
        "scheduledAt": interview_at.isoformat(),
        "type": "onsite",
        "location": "ACME Kocaeli Fabrikası",
        "note": "Güvenlik girişinde kimlik gösterin.",
        "updatedAt": updated_application["interview"]["updatedAt"],
        "response": None,
    }

    application_dashboard = client.get(
        f"/api/users/{user_id}/dashboard"
    ).get_json()
    dashboard_application = application_dashboard["jobApplications"][0]
    assert dashboard_application["status"] == "shortlisted"
    assert (
        dashboard_application["statusHistory"][-1]["note"]
        == "Telefon görüşmesine alınacak."
    )
    assert (
        dashboard_application["interview"]["scheduledAt"]
        == interview_at.isoformat()
    )

    invalid_interview_response = client.post(
        f"/api/users/{user_id}/job-applications/"
        f"{application['id']}/interview-response",
        json={"status": "maybe"},
        headers={"Idempotency-Key": "invalid-interview-response"},
    )
    non_string_interview_response = client.post(
        f"/api/users/{user_id}/job-applications/"
        f"{application['id']}/interview-response",
        json={"status": ["confirmed"]},
        headers={
            "Idempotency-Key": "non-string-interview-response"
        },
    )
    declined_without_note = client.post(
        f"/api/users/{user_id}/job-applications/"
        f"{application['id']}/interview-response",
        json={"status": "declined"},
        headers={"Idempotency-Key": "decline-without-note"},
    )
    confirmed_interview = client.post(
        f"/api/users/{user_id}/job-applications/"
        f"{application['id']}/interview-response",
        json={"status": "confirmed"},
        headers={"Idempotency-Key": "confirm-interview"},
    )
    confirmed_interview_replay = client.post(
        f"/api/users/{user_id}/job-applications/"
        f"{application['id']}/interview-response",
        json={"status": "confirmed"},
        headers={"Idempotency-Key": "confirm-interview"},
    )
    assert invalid_interview_response.status_code == 400
    assert non_string_interview_response.status_code == 400
    assert declined_without_note.status_code == 400
    assert confirmed_interview.status_code == 200
    confirmed_response = confirmed_interview.get_json()[
        "jobApplication"
    ]["interview"]["response"]
    assert confirmed_response["status"] == "confirmed"
    assert confirmed_response["note"] == ""
    assert confirmed_response["respondedAt"]
    assert (
        confirmed_interview_replay.get_json()["jobApplication"]
        ["interview"]["response"]
        == confirmed_response
    )

    rescheduled_at = interview_at + timedelta(days=1)
    rescheduled = client.patch(
        f"/api/employers/acme/job-applications/{application['id']}",
        json={
            "status": "shortlisted",
            "interview": {
                "scheduledAt": rescheduled_at.isoformat(),
                "type": "video",
                "location": "Mobil görüşme bağlantısı SMS ile iletilecek",
                "note": "Sessiz bir ortamda hazır olun.",
            },
        },
    )
    invalid_interview = client.patch(
        f"/api/employers/acme/job-applications/{application['id']}",
        json={
            "status": "shortlisted",
            "interview": {
                "scheduledAt": interview_at.isoformat(),
                "type": "onsite",
                "location": "",
            },
        },
    )
    assert rescheduled.status_code == 200
    assert (
        rescheduled.get_json()["jobApplication"]["interview"]["type"]
        == "video"
    )
    assert (
        rescheduled.get_json()["jobApplication"]["interview"]
        ["response"]
        is None
    )
    assert (
        rescheduled.get_json()["jobApplication"]
        ["statusHistory"][-1]["note"]
        == "Görüşme planı güncellendi."
    )
    assert invalid_interview.status_code == 400

    declined_interview = client.post(
        f"/api/users/{user_id}/job-applications/"
        f"{application['id']}/interview-response",
        json={
            "status": "declined",
            "note": "Bu saatte vardiyadayım, yeniden planlayabilir miyiz?",
        },
        headers={"Idempotency-Key": "decline-rescheduled-interview"},
    )
    assert declined_interview.status_code == 200
    declined_response = declined_interview.get_json()[
        "jobApplication"
    ]["interview"]["response"]
    assert declined_response["status"] == "declined"
    assert (
        declined_response["note"]
        == "Bu saatte vardiyadayım, yeniden planlayabilir miyiz?"
    )
    employer_after_response = client.get(
        "/api/employers/acme/job-applications"
    ).get_json()["jobApplications"][0]
    assert (
        employer_after_response["interview"]["response"]
        == declined_response
    )

    another_user = client.post(
        "/api/users",
        json={"phone": "+905554445501"},
    ).get_json()["user"]
    foreign_interview_response = client.post(
        f"/api/users/{another_user['id']}/job-applications/"
        f"{application['id']}/interview-response",
        json={"status": "confirmed"},
        headers={"Idempotency-Key": "foreign-interview-response"},
    )
    assert foreign_interview_response.status_code == 404

    user_payload = client.get(
        f"/api/users/{user_id}/job-applications"
    ).get_json()
    user_applications = user_payload["jobApplications"]
    assert user_applications[0]["status"] == "shortlisted"
    assert (
        user_applications[0]["interview"]["scheduledAt"]
        == rescheduled_at.isoformat()
    )
    assert (
        user_applications[0]["interview"]["response"]["status"]
        == "declined"
    )
    assert user_payload["pagination"]["total"] == 1
    cleared_interview = client.patch(
        f"/api/employers/acme/job-applications/{application['id']}",
        json={
            "status": "shortlisted",
            "interview": None,
        },
    )
    assert cleared_interview.status_code == 200
    assert (
        cleared_interview.get_json()["jobApplication"]["interview"]
        is None
    )
    assert (
        cleared_interview.get_json()["jobApplication"]
        ["statusHistory"][-1]["note"]
        == "Görüşme planı kaldırıldı."
    )

    foreign_withdrawal = client.post(
        f"/api/users/{another_user['id']}/job-applications/"
        f"{application['id']}/withdraw",
    )
    assert foreign_withdrawal.status_code == 404

    withdrawal = client.post(
        f"/api/users/{user_id}/job-applications/"
        f"{application['id']}/withdraw",
    )
    repeated_withdrawal = client.post(
        f"/api/users/{user_id}/job-applications/"
        f"{application['id']}/withdraw",
    )
    assert withdrawal.status_code == 200
    assert (
        withdrawal.get_json()["jobApplication"]["status"]
        == "withdrawn"
    )
    assert repeated_withdrawal.status_code == 200
    assert (
        withdrawal.get_json()["jobApplication"]
        ["statusHistory"][-1]["note"]
        == "Çalışan başvurusunu geri çekti."
    )

    employer_reopen = client.patch(
        f"/api/employers/acme/job-applications/"
        f"{application['id']}",
        json={"status": "reviewing"},
    )
    assert employer_reopen.status_code == 409
    withdrawn_dashboard = client.get(
        f"/api/users/{user_id}/dashboard"
    ).get_json()
    assert (
        withdrawn_dashboard["jobApplications"][0]["status"]
        == "withdrawn"
    )
    withdrawn_filter = client.get(
        "/api/employers/acme/job-applications"
        "?status=withdrawn"
    ).get_json()
    assert withdrawn_filter["pagination"]["total"] == 1


def test_employer_job_postings_drive_worker_recommendations(app, client):
    app.config["TRANSCRIPTION_STATIC_TEXT"] = (
        "Adım Mehmet Yılmaz. Kaynak işlerinde deneyimliyim, iş güvenliği "
        "kurallarına uyarım ve vardiyalı çalışabilirim."
    )
    posting_response = client.post(
        "/api/employers/acme/job-postings",
        json={
            "title": "Kaynak Operatörü",
            "company": "ACME Üretim",
            "location": "Kocaeli",
            "description": "Üretim hattında kaynak operasyonlarını yürütür.",
            "requiredSkills": ["kaynak", "iş güvenliği"],
            "optionalSkills": ["vardiya uyumu"],
            "status": "published",
            "employmentType": "full_time",
            "shift": "rotating",
            "openings": 4,
        },
    )
    invalid_posting = client.post(
        "/api/employers/acme/job-postings",
        json={
            "title": "Eksik İlan",
            "location": "Kocaeli",
            "description": "Eksik beceri listesi.",
            "requiredSkills": [],
        },
    )
    assert posting_response.status_code == 201
    assert invalid_posting.status_code == 400
    posting = posting_response.get_json()["jobPosting"]

    user = client.post(
        "/api/users",
        json={"phone": "+905554445511", "employerKey": "acme"},
    ).get_json()["user"]
    client.post(
        f"/api/users/{user['id']}/videos",
        data={"video": (BytesIO(b"job posting video"), "welding.mp4")},
        content_type="multipart/form-data",
    )
    dashboard = client.get(
        f"/api/users/{user['id']}/dashboard"
    ).get_json()

    assert len(dashboard["recommendedJobs"]) == 1
    recommendation = dashboard["recommendedJobs"][0]
    assert recommendation["jobPostingId"] == posting["id"]
    assert recommendation["title"] == "Kaynak Operatörü"
    assert recommendation["company"] == "ACME Üretim"
    assert recommendation["matchScore"] == 94

    application = client.post(
        f"/api/users/{user['id']}/job-applications",
        json={"jobRecommendationId": recommendation["id"]},
    )
    assert application.status_code == 201
    assert (
        application.get_json()["jobApplication"]["jobPostingId"]
        == posting["id"]
    )
    application_id = application.get_json()["jobApplication"]["id"]

    client.post(
        f"/api/users/{user['id']}/videos",
        data={"video": (BytesIO(b"updated video"), "updated.mp4")},
        content_type="multipart/form-data",
    )
    refreshed_recommendation = client.get(
        f"/api/users/{user['id']}/dashboard"
    ).get_json()["recommendedJobs"][0]
    duplicate_for_posting = client.post(
        f"/api/users/{user['id']}/job-applications",
        json={"jobRecommendationId": refreshed_recommendation["id"]},
    )
    assert duplicate_for_posting.status_code == 200
    assert (
        duplicate_for_posting.get_json()["jobApplication"]["id"]
        == application_id
    )
    assert refreshed_recommendation["applicationId"] == application_id

    hired = client.patch(
        f"/api/employers/acme/job-applications/{application_id}",
        json={"status": "hired"},
    )
    invalid_reopen = client.patch(
        f"/api/employers/acme/job-applications/{application_id}",
        json={"status": "submitted"},
    )
    assert hired.status_code == 200
    assert invalid_reopen.status_code == 409

    delete_with_application = client.delete(
        f"/api/employers/acme/job-postings/{posting['id']}"
    )
    close_posting = client.patch(
        f"/api/employers/acme/job-postings/{posting['id']}",
        json={"status": "closed"},
    )
    refreshed_dashboard = client.get(
        f"/api/users/{user['id']}/dashboard"
    ).get_json()

    assert delete_with_application.status_code == 409
    assert close_posting.status_code == 200
    assert close_posting.get_json()["jobPosting"]["status"] == "closed"
    assert all(
        item["jobPostingId"] != posting["id"]
        for item in refreshed_dashboard["recommendedJobs"]
    )


def test_hiring_capacity_uses_atomic_slots(app, client):
    posting = client.post(
        "/api/employers/acme/job-postings",
        json={
            "title": "Tek Kontenjanlı Kaynakçı",
            "company": "ACME Üretim",
            "location": "Kocaeli",
            "description": "Kaynak hattında görev alır.",
            "requiredSkills": ["kaynak"],
            "optionalSkills": [],
            "status": "published",
            "employmentType": "full_time",
            "shift": "day",
            "openings": 1,
        },
    ).get_json()["jobPosting"]

    application_ids = []
    for index in range(2):
        worker = client.post(
            "/api/users",
            json={
                "phone": f"+9055510203{index:02d}",
                "employerKey": "acme",
            },
        ).get_json()["user"]
        client.post(
            f"/api/users/{worker['id']}/videos",
            data={
                "video": (
                    BytesIO(f"worker-{index}".encode()),
                    f"worker-{index}.mp4",
                )
            },
            content_type="multipart/form-data",
        )
        recommendation = client.get(
            f"/api/users/{worker['id']}/dashboard"
        ).get_json()["recommendedJobs"][0]
        application = client.post(
            f"/api/users/{worker['id']}/job-applications",
            json={"jobRecommendationId": recommendation["id"]},
        ).get_json()["jobApplication"]
        application_ids.append(application["id"])

    first_hire = client.patch(
        f"/api/employers/acme/job-applications/{application_ids[0]}",
        json={"status": "hired"},
    )
    capacity_reached = client.patch(
        f"/api/employers/acme/job-applications/{application_ids[1]}",
        json={"status": "hired"},
    )

    assert first_hire.status_code == 200
    assert first_hire.get_json()["jobApplication"]["hiringSlot"] == 1
    assert capacity_reached.status_code == 409
    with app.app_context():
        assert get_db().jobHiringSlots.count_documents(
            {"jobPostingId": ObjectId(posting["id"])}
        ) == 1

    increased = client.patch(
        f"/api/employers/acme/job-postings/{posting['id']}",
        json={"openings": 2},
    )
    second_hire = client.patch(
        f"/api/employers/acme/job-applications/{application_ids[1]}",
        json={"status": "hired"},
    )
    decrease = client.patch(
        f"/api/employers/acme/job-postings/{posting['id']}",
        json={"openings": 1},
    )

    assert increased.status_code == 200
    assert second_hire.status_code == 200
    assert second_hire.get_json()["jobApplication"]["hiringSlot"] == 2
    assert decrease.status_code == 409


def test_employer_worker_config_and_question_answering(client):
    update = client.put(
        "/api/employers/acme/worker-config",
        json={
            "assessments": [
                {
                    "id": "welding-check",
                    "title": "Kaynak Ustalığı Kontrolü",
                    "description": "Kaynak işine başlamadan önce tamamlanır.",
                    "status": "available",
                    "durationMinutes": 15,
                    "required": True,
                    "passScore": 70,
                    "questions": [
                        {
                            "id": "welding-safety",
                            "prompt": "Kaynak öncesinde ilk kontrol nedir?",
                            "options": [
                                {
                                    "id": "ppe",
                                    "label": "Koruyucu ekipman",
                                    "score": 100,
                                },
                                {
                                    "id": "phone",
                                    "label": "Telefon şarjı",
                                    "score": 0,
                                },
                            ],
                        }
                    ],
                }
            ],
            "trainings": [],
            "usefulInfo": [],
            "shuttle": {"enabled": True, "title": "ACME Servis", "routes": []},
            "qaKnowledgeBase": [
                {"keywords": ["servis"], "answer": "ACME servis kaydın vardiya planına göre yapılır."}
            ],
        },
    )
    assert update.status_code == 200

    user_response = client.post(
        "/api/users",
        json={"phone": "+905551010101", "employerKey": "acme"},
    )
    user = user_response.get_json()["user"]

    dashboard = client.get(f"/api/users/{user['id']}/dashboard").get_json()
    assert dashboard["workerHub"]["employerKey"] == "acme"
    assert dashboard["workerHub"]["assessments"][0]["id"] == "welding-check"

    answer = client.post(
        f"/api/users/{user['id']}/questions",
        json={"question": "Servis kaydımı nasıl yapacağım?"},
    )
    assert answer.status_code == 201
    assert answer.get_json()["answer"]["answer"] == "ACME servis kaydın vardiya planına göre yapılır."
    assert answer.get_json()["answer"]["status"] == "auto_answered"

    updated_dashboard = client.get(f"/api/users/{user['id']}/dashboard").get_json()
    assert updated_dashboard["recentQuestions"][0]["question"] == "Servis kaydımı nasıl yapacağım?"
    assert updated_dashboard["recentQuestions"][0]["answer"] == "ACME servis kaydın vardiya planına göre yapılır."

    pending = client.post(
        f"/api/users/{user['id']}/questions",
        json={"question": "Fazla mesai ücretim ne zaman ödenecek?"},
    )
    assert pending.status_code == 201
    pending_question = pending.get_json()["answer"]
    assert pending_question["status"] == "pending"
    pending_dashboard = client.get(
        f"/api/users/{user['id']}/dashboard"
    ).get_json()
    assert pending_dashboard["pendingQuestionCount"] == 1

    employer_questions = client.get(
        "/api/employers/acme/questions?status=pending"
    ).get_json()
    assert employer_questions["pagination"]["total"] == 1
    assert employer_questions["questions"][0]["worker"]["phone"] == "+905551010101"

    employer_answer = client.patch(
        f"/api/employers/acme/questions/{pending_question['id']}",
        json={"answer": "Fazla mesai ödemesi takip eden ayın bordrosuna eklenir."},
    )
    assert employer_answer.status_code == 200
    assert employer_answer.get_json()["question"]["status"] == "answered"

    answered_dashboard = client.get(
        f"/api/users/{user['id']}/dashboard"
    ).get_json()
    assert answered_dashboard["recentQuestions"][0]["answer"] == (
        "Fazla mesai ödemesi takip eden ayın bordrosuna eklenir."
    )
    assert answered_dashboard["recentQuestions"][0]["status"] == "answered"
    assert answered_dashboard["pendingQuestionCount"] == 0


def test_worker_questions_are_rate_limited_per_worker(app, client):
    app.config.update(
        WORKER_QUESTION_RATE_LIMIT_WINDOW_SECONDS=60,
        WORKER_QUESTION_MAX_REQUESTS=2,
    )
    user = client.post(
        "/api/users",
        json={"phone": "+905551010102", "employerKey": "acme"},
    ).get_json()["user"]

    responses = [
        client.post(
            f"/api/users/{user['id']}/questions",
            json={"question": f"İşveren sorusu {index + 1}"},
        )
        for index in range(3)
    ]

    assert [response.status_code for response in responses] == [
        201,
        201,
        429,
    ]
    assert int(responses[-1].headers["Retry-After"]) > 0
    with app.app_context():
        assert get_db().workerQuestions.count_documents(
            {"userId": ObjectId(user["id"])}
        ) == 2


def test_employer_can_manage_worker_config_items(client):
    assessment_payload = {
        "id": "forklift-readiness",
        "title": "Forklift Hazırlık",
        "description": "Güvenli forklift kullanımını değerlendirir.",
        "durationMinutes": 10,
        "required": True,
        "passScore": 80,
        "questions": [
            {
                "id": "daily-check",
                "prompt": "Vardiya öncesinde ne yapılır?",
                "options": [
                    {
                        "id": "inspect",
                        "label": "Günlük ekipman kontrolü",
                        "score": 100,
                    },
                    {
                        "id": "start",
                        "label": "Doğrudan işe başlama",
                        "score": 0,
                    },
                ],
            }
        ],
    }
    assessment = client.post(
        "/api/employers/acme/worker-config/assessments",
        json=assessment_payload,
    )
    duplicate = client.post(
        "/api/employers/acme/worker-config/assessments",
        json=assessment_payload,
    )

    assert assessment.status_code == 201
    assert assessment.get_json()["item"]["id"] == "forklift-readiness"
    assert duplicate.status_code == 409

    assessment_update = client.patch(
        "/api/employers/acme/worker-config/assessments/forklift-readiness",
        json={"title": "Forklift Güvenlik Hazırlığı"},
    )
    assert assessment_update.status_code == 200
    assert assessment_update.get_json()["item"]["title"] == "Forklift Güvenlik Hazırlığı"

    training = client.post(
        "/api/employers/acme/worker-config/trainings",
        json={
            "id": "forklift-101",
            "title": "Forklift 101",
            "description": "Temel kullanım eğitimi.",
            "durationMinutes": 30,
            "modules": [
                {
                    "id": "inspection",
                    "title": "Günlük kontrol",
                    "body": "Ekipmanı vardiya öncesinde kontrol et.",
                }
            ],
        },
    )
    useful_info = client.post(
        "/api/employers/acme/worker-config/useful-info",
        json={
            "title": "İlk vardiya",
            "body": "Vardiya başlangıcından 15 dakika önce sahada ol.",
            "category": "onboarding",
        },
    )
    qa = client.post(
        "/api/employers/acme/worker-config/qa-knowledge",
        json={
            "keywords": ["yemek", "yemekhane"],
            "answer": "Yemekhane zemin kattadır.",
        },
    )
    shuttle_settings = client.patch(
        "/api/employers/acme/worker-config/shuttle",
        json={
            "enabled": True,
            "title": "ACME Servisleri",
            "description": "Güncel servis güzergahları.",
        },
    )
    shuttle_route = client.post(
        "/api/employers/acme/worker-config/shuttle/routes",
        json={
            "id": "acme-route-1",
            "name": "Merkez - Fabrika",
            "pickupWindow": "06:45 - 07:15",
        },
    )

    assert training.status_code == 201
    assert useful_info.status_code == 201
    assert useful_info.get_json()["item"]["id"].startswith("info-")
    assert qa.status_code == 201
    assert qa.get_json()["item"]["id"].startswith("qa-")
    assert shuttle_settings.status_code == 200
    assert shuttle_route.status_code == 201

    route_update = client.patch(
        "/api/employers/acme/worker-config/shuttle/routes/acme-route-1",
        json={"pickupWindow": "07:00 - 07:30"},
    )
    assert route_update.status_code == 200
    assert route_update.get_json()["item"]["pickupWindow"] == "07:00 - 07:30"

    config = client.get(
        "/api/employers/acme/worker-config"
    ).get_json()["workerConfig"]
    assert config["schemaVersion"] == 2
    assert any(item["id"] == "forklift-readiness" for item in config["assessments"])
    assert any(item["id"] == "forklift-101" for item in config["trainings"])
    assert any(item["category"] == "onboarding" for item in config["usefulInfo"])
    assert any(item["keywords"] == ["yemek", "yemekhane"] for item in config["qaKnowledgeBase"])
    assert any(item["id"] == "acme-route-1" for item in config["shuttle"]["routes"])

    deleted = client.delete(
        "/api/employers/acme/worker-config/assessments/forklift-readiness"
    )
    assert deleted.status_code == 200
    assert all(
        item["id"] != "forklift-readiness"
        for item in deleted.get_json()["workerConfig"]["assessments"]
    )


def test_worker_config_management_rejects_invalid_payloads(client):
    missing_questions = client.post(
        "/api/employers/acme/worker-config/assessments",
        json={
            "title": "Eksik Değerlendirme",
            "durationMinutes": 10,
            "questions": [],
        },
    )
    unknown_field = client.post(
        "/api/employers/acme/worker-config/useful-info",
        json={
            "title": "Bilgi",
            "body": "İçerik",
            "category": "general",
            "unexpected": True,
        },
    )
    invalid_body = client.post(
        "/api/employers/acme/worker-config/trainings",
        json=[],
    )
    unsupported_resource = client.post(
        "/api/employers/acme/worker-config/unknown",
        json={"id": "item"},
    )

    assert missing_questions.status_code == 400
    assert unknown_field.status_code == 400
    assert invalid_body.status_code == 400
    assert unsupported_resource.status_code == 404


def test_employer_assigns_available_support_content_to_one_worker(
    client,
):
    config = client.put(
        "/api/employers/acme/worker-config",
        json={
            "assessments": [
                {
                    "id": "safety",
                    "title": "İSG Kontrolü",
                    "description": "İşe başlamadan önce tamamlanır.",
                    "status": "available",
                    "durationMinutes": 10,
                    "required": True,
                    "passScore": 70,
                    "questions": [
                        {
                            "id": "safe-start",
                            "prompt": "İlk adım nedir?",
                            "options": [
                                {
                                    "id": "check-ppe",
                                    "label": "Ekipmanı kontrol et",
                                    "score": 100,
                                },
                                {
                                    "id": "start-now",
                                    "label": "Hemen başla",
                                    "score": 0,
                                },
                            ],
                        }
                    ],
                },
                {
                    "id": "draft-assessment",
                    "title": "Taslak değerlendirme",
                    "description": "Henüz yayınlanmadı.",
                    "status": "draft",
                    "durationMinutes": 5,
                    "required": False,
                    "passScore": 50,
                    "questions": [
                        {
                            "id": "draft-question",
                            "prompt": "Taslak soru",
                            "options": [
                                {
                                    "id": "yes",
                                    "label": "Evet",
                                    "score": 100,
                                },
                                {
                                    "id": "no",
                                    "label": "Hayır",
                                    "score": 0,
                                },
                            ],
                        }
                    ],
                },
            ],
            "trainings": [
                {
                    "id": "orientation",
                    "title": "Saha Oryantasyonu",
                    "description": "Saha kurallarını açıklar.",
                    "status": "available",
                    "durationMinutes": 20,
                    "modules": [
                        {
                            "id": "site-rules",
                            "title": "Saha kuralları",
                            "body": "İşaretli alanlarda yürüyün.",
                        }
                    ],
                },
                {
                    "id": "equipment",
                    "title": "Ekipman Eğitimi",
                    "description": "Ekipman kullanımını açıklar.",
                    "status": "available",
                    "durationMinutes": 30,
                    "modules": [
                        {
                            "id": "inspection",
                            "title": "Kontrol",
                            "body": "Ekipmanı vardiya öncesi kontrol edin.",
                        }
                    ],
                },
            ],
        },
    )
    assert config.status_code == 200
    worker = client.post(
        "/api/users",
        json={
            "phone": "+905551010188",
            "employerKey": "acme",
        },
    ).get_json()["user"]

    default_assignments = client.get(
        "/api/employers/acme/workers/"
        f"{worker['id']}/support-assignments"
    ).get_json()["supportAssignments"]
    default_dashboard = client.get(
        f"/api/users/{worker['id']}/dashboard"
    ).get_json()

    assert default_assignments["customized"] is False
    assert default_assignments["assessmentIds"] == ["safety"]
    assert default_assignments["trainingIds"] == [
        "orientation",
        "equipment",
    ]
    assert [
        item["id"]
        for item in default_assignments["catalog"]["assessments"]
    ] == ["safety"]
    assert [
        item["id"]
        for item in default_dashboard["workerHub"]["assessments"]
    ] == ["safety"]

    invalid_assignment = client.put(
        "/api/employers/acme/workers/"
        f"{worker['id']}/support-assignments",
        json={
            "assessmentIds": ["draft-assessment"],
            "trainingIds": [],
        },
    )
    saved = client.put(
        "/api/employers/acme/workers/"
        f"{worker['id']}/support-assignments",
        json={
            "assessmentIds": [],
            "trainingIds": ["equipment"],
        },
    )
    filtered_dashboard = client.get(
        f"/api/users/{worker['id']}/dashboard"
    ).get_json()
    blocked_assessment = client.post(
        f"/api/users/{worker['id']}/assessments/safety/complete",
        json={
            "answers": [
                {
                    "questionId": "safe-start",
                    "optionId": "check-ppe",
                }
            ]
        },
    )
    blocked_training = client.post(
        f"/api/users/{worker['id']}/trainings/orientation/complete",
        json={"completedModules": ["site-rules"]},
    )
    completed_training = client.post(
        f"/api/users/{worker['id']}/trainings/equipment/complete",
        json={"completedModules": ["inspection"]},
    )

    assert invalid_assignment.status_code == 400
    assert saved.status_code == 200
    saved_assignments = saved.get_json()["supportAssignments"]
    assert saved_assignments["customized"] is True
    assert saved_assignments["assessmentIds"] == []
    assert saved_assignments["trainingIds"] == ["equipment"]
    assert filtered_dashboard["workerHub"]["assessments"] == []
    assert [
        item["id"]
        for item in filtered_dashboard["workerHub"]["trainings"]
    ] == ["equipment"]
    assert blocked_assessment.status_code == 404
    assert blocked_training.status_code == 404
    assert completed_training.status_code == 201


def test_deleted_default_config_item_is_not_backfilled_again(client):
    initial = client.get(
        "/api/employers/default/worker-config"
    ).get_json()["workerConfig"]
    assert initial["schemaVersion"] == 2
    assert any(item["id"] == "safety-readiness" for item in initial["assessments"])

    deleted = client.delete(
        "/api/employers/default/worker-config/assessments/safety-readiness"
    )
    refreshed = client.get(
        "/api/employers/default/worker-config"
    ).get_json()["workerConfig"]

    assert deleted.status_code == 200
    assert all(item["id"] != "safety-readiness" for item in refreshed["assessments"])


def test_default_worker_config_backfills_new_fields(app, client):
    with app.app_context():
        db = get_db()
        db.workerSupportConfigs.insert_one(
            {
                "employerKey": "default",
                "assessments": [
                    {
                        "id": "safety-readiness",
                        "title": "Eski İSG Değerlendirmesi",
                        "description": "Eski kayıt",
                        "status": "available",
                        "durationMinutes": 5,
                        "required": True,
                    }
                ],
                "trainings": [
                    {
                        "id": "isg-101",
                        "title": "Eski İSG Eğitimi",
                        "description": "Eski eğitim",
                        "durationMinutes": 10,
                        "status": "available",
                    }
                ],
                "usefulInfo": [],
                "shuttle": {"enabled": True, "routes": []},
                "qaKnowledgeBase": [],
            }
        )

    user_response = client.post("/api/users", json={"phone": "+905553333444"})
    user_id = user_response.get_json()["user"]["id"]

    hub = client.get(f"/api/users/{user_id}/worker-hub").get_json()["workerHub"]

    assert hub["assessments"][0]["title"] == "Eski İSG Değerlendirmesi"
    assert hub["assessments"][0]["questions"]
    assert hub["assessments"][0]["passScore"] == 70
    assert hub["trainings"][0]["title"] == "Eski İSG Eğitimi"
    assert hub["trainings"][0]["modules"]


def test_assessment_completion_rejects_missing_or_invalid_answers(client):
    user_response = client.post("/api/users", json={"phone": "+905559999888"})
    user_id = user_response.get_json()["user"]["id"]

    missing_answer = client.post(
        f"/api/users/{user_id}/assessments/safety-readiness/complete",
        json={
            "answers": [
                {"questionId": "ppe-check", "optionId": "ppe-complete"},
            ],
            "score": 100,
        },
    )
    invalid_option = client.post(
        f"/api/users/{user_id}/assessments/safety-readiness/complete",
        json={
            "answers": [
                {"questionId": "ppe-check", "optionId": "invalid"},
                {
                    "questionId": "unsafe-condition",
                    "optionId": "notify-supervisor",
                },
            ]
        },
    )

    assert missing_answer.status_code == 400
    assert invalid_option.status_code == 400


def test_worker_actions_update_hub_status(client):
    user_response = client.post("/api/users", json={"phone": "+905552222333"})
    user_id = user_response.get_json()["user"]["id"]

    assessment = client.post(
        f"/api/users/{user_id}/assessments/safety-readiness/complete",
        json={
            "answers": [
                {"questionId": "ppe-check", "optionId": "ppe-complete"},
                {"questionId": "unsafe-condition", "optionId": "notify-supervisor"},
            ]
        },
    )
    failed_assessment = client.post(
        f"/api/users/{user_id}/assessments/role-fit/complete",
        json={
            "answers": [
                {
                    "questionId": "shift-fit",
                    "optionId": "day-only",
                },
                {
                    "questionId": "team-fit",
                    "optionId": "solo-work",
                },
            ]
        },
    )
    passed_retake = client.post(
        f"/api/users/{user_id}/assessments/role-fit/complete",
        json={
            "answers": [
                {
                    "questionId": "shift-fit",
                    "optionId": "shift-ready",
                },
                {
                    "questionId": "team-fit",
                    "optionId": "team-communicate",
                },
            ]
        },
    )
    partial_training = client.put(
        f"/api/users/{user_id}/trainings/isg-101/progress",
        json={"completedModules": ["ppe"]},
    )
    invalid_partial_training = client.put(
        f"/api/users/{user_id}/trainings/isg-101/progress",
        json={"completedModules": ["unknown"]},
    )
    incomplete_training = client.post(
        f"/api/users/{user_id}/trainings/isg-101/complete",
        json={"completedModules": ["ppe"]},
    )
    duplicate_training_module = client.post(
        f"/api/users/{user_id}/trainings/isg-101/complete",
        json={"completedModules": ["ppe", "ppe"]},
    )
    unknown_training_module = client.post(
        f"/api/users/{user_id}/trainings/isg-101/complete",
        json={"completedModules": ["ppe", "unknown"]},
    )
    training = client.post(
        f"/api/users/{user_id}/trainings/isg-101/complete",
        json={
            "completedModules": ["emergency", "ppe"],
            "progressPercent": 1,
        },
    )
    completed_training_reduction = client.put(
        f"/api/users/{user_id}/trainings/isg-101/progress",
        json={"completedModules": ["ppe"]},
    )
    shuttle = client.post(
        f"/api/users/{user_id}/shuttle-requests",
        json={"routeId": "route-1", "pickupNote": "Ana duraktan bineceğim."},
    )

    assert assessment.status_code == 201
    assert assessment.get_json()["assessment"]["status"] == "completed"
    assert assessment.get_json()["assessment"]["score"] == 100
    assert assessment.get_json()["assessment"]["passed"] is True
    assert failed_assessment.status_code == 201
    assert failed_assessment.get_json()["assessment"]["passed"] is False
    assert (
        failed_assessment.get_json()["assessment"]["attemptCount"]
        == 1
    )
    assert passed_retake.status_code == 201
    retake_result = passed_retake.get_json()["assessment"]
    assert retake_result["passed"] is True
    assert retake_result["attemptCount"] == 2
    assert len(retake_result["attemptHistory"]) == 2
    assert retake_result["attemptHistory"][0]["passed"] is False
    assert retake_result["attemptHistory"][1]["passed"] is True
    assert partial_training.status_code == 200
    assert (
        partial_training.get_json()["training"]["status"]
        == "in_progress"
    )
    assert (
        partial_training.get_json()["training"]["progressPercent"]
        == 50
    )
    assert invalid_partial_training.status_code == 400
    assert incomplete_training.status_code == 400
    assert duplicate_training_module.status_code == 400
    assert unknown_training_module.status_code == 400
    assert training.status_code == 201
    assert training.get_json()["training"]["progressPercent"] == 100
    assert training.get_json()["training"]["completedModules"] == ["ppe", "emergency"]
    assert completed_training_reduction.status_code == 409
    assert shuttle.status_code == 201
    assert shuttle.get_json()["shuttleRequest"]["routeId"] == "route-1"

    shuttle_payload = client.get(
        "/api/employers/default/shuttle-requests?limit=1"
    ).get_json()
    employer_shuttles = shuttle_payload["shuttleRequests"]
    assert employer_shuttles[0]["routeId"] == "route-1"
    assert employer_shuttles[0]["worker"]["phone"] == "+905552222333"
    assert shuttle_payload["pagination"]["total"] == 1
    invalid_page = client.get(
        "/api/employers/default/shuttle-requests?page=invalid"
    )
    assert invalid_page.status_code == 400

    shuttle_decision = client.patch(
        f"/api/employers/default/shuttle-requests/{employer_shuttles[0]['id']}",
        json={"status": "confirmed", "decisionNote": "Durak sorumlusu bilgilendirildi."},
    )
    assert shuttle_decision.status_code == 200
    assert shuttle_decision.get_json()["shuttleRequest"]["status"] == "confirmed"
    invalid_transition = client.patch(
        f"/api/employers/default/shuttle-requests/{employer_shuttles[0]['id']}",
        json={"status": "requested"},
    )
    invalid_note = client.patch(
        f"/api/employers/default/shuttle-requests/{employer_shuttles[0]['id']}",
        json={"status": "rejected", "decisionNote": 42},
    )
    assert invalid_transition.status_code == 400
    assert invalid_note.status_code == 400

    replacement = client.post(
        f"/api/users/{user_id}/shuttle-requests",
        json={
            "routeId": "route-2",
            "pickupNote": "Kartal durağından bineceğim.",
        },
    )
    replacement_request = replacement.get_json()["shuttleRequest"]
    assert replacement.status_code == 201
    assert replacement_request["routeId"] == "route-2"

    another_user = client.post(
        "/api/users",
        json={"phone": "+905552222334"},
    ).get_json()["user"]
    foreign_cancel = client.post(
        f"/api/users/{another_user['id']}/shuttle-requests/"
        f"{replacement_request['id']}/cancel",
    )
    assert foreign_cancel.status_code == 404

    cancelled = client.post(
        f"/api/users/{user_id}/shuttle-requests/"
        f"{replacement_request['id']}/cancel",
    )
    assert cancelled.status_code == 200
    assert (
        cancelled.get_json()["shuttleRequest"]["status"]
        == "cancelled"
    )
    assert (
        cancelled.get_json()["shuttleRequest"]["cancelledAt"]
        is not None
    )
    cancelled_filter = client.get(
        "/api/employers/default/shuttle-requests"
        "?status=cancelled"
    ).get_json()
    assert cancelled_filter["pagination"]["total"] == 1
    assert cancelled_filter["shuttleRequests"][0]["id"] == (
        replacement_request["id"]
    )

    hub = client.get(f"/api/users/{user_id}/worker-hub").get_json()["workerHub"]
    assert hub["assessments"][0]["status"] == "completed"
    assert hub["assessments"][0]["score"] == 100
    assert hub["assessments"][0]["answers"][0]["questionId"] == "ppe-check"
    role_fit = next(
        item
        for item in hub["assessments"]
        if item["id"] == "role-fit"
    )
    assert role_fit["passed"] is True
    assert role_fit["attemptCount"] == 2
    assert hub["trainings"][0]["status"] == "completed"
    assert hub["trainings"][0]["completedModules"] == ["ppe", "emergency"]
    assert hub["shuttle"]["requestId"] == replacement_request["id"]
    assert hub["shuttle"]["selectedRouteId"] == "route-2"
    assert hub["shuttle"]["requestStatus"] == "cancelled"
    assert hub["shuttle"]["pickupNote"] == "Kartal durağından bineceğim."

    with client.application.app_context():
        replaced_request = get_db().workerShuttleRequests.find_one(
            {"_id": ObjectId(employer_shuttles[0]["id"])}
        )
        assert replaced_request["status"] == "replaced"


def test_worker_device_registration_rotates_and_revokes_tokens(
    app,
    client,
):
    first_user = client.post(
        "/api/users", json={"phone": "+905551112244"}
    ).get_json()["user"]
    second_user = client.post(
        "/api/users", json={"phone": "+905551112255"}
    ).get_json()["user"]
    first_installation = (
        "33333333-3333-4333-8333-333333333333"
    )
    second_installation = (
        "44444444-4444-4444-8444-444444444444"
    )
    first_url = (
        f"/api/users/{first_user['id']}/devices/"
        f"{first_installation}"
    )
    second_url = (
        f"/api/users/{second_user['id']}/devices/"
        f"{second_installation}"
    )
    first_fid = "firebase-device-fid-first-000001"
    rotated_fid = "firebase-device-fid-rotated-0002"

    first = client.put(
        first_url,
        json={
            "fid": first_fid,
            "platform": "android",
            "appVersionCode": 1,
            "appVersionName": "1.0",
        },
    )
    rotated = client.put(
        first_url,
        json={
            "fid": rotated_fid,
            "platform": "android",
            "appVersionCode": 2,
            "appVersionName": "1.1",
        },
    )
    reassigned = client.put(
        second_url,
        json={
            "fid": rotated_fid,
            "platform": "android",
            "appVersionCode": 3,
            "appVersionName": "1.2",
        },
    )
    invalid = client.put(
        (
            f"/api/users/{second_user['id']}/devices/"
            "not-an-installation-id"
        ),
        json={
            "fid": "short",
            "platform": "android",
            "appVersionCode": 1,
            "appVersionName": "1.0",
        },
    )
    removed = client.delete(second_url)

    assert first.status_code == 200
    assert rotated.status_code == 200
    assert rotated.get_json()["device"]["appVersionCode"] == 2
    assert reassigned.status_code == 200
    assert invalid.status_code == 400
    assert removed.status_code == 204
    for response in (first, rotated, reassigned):
        serialized = response.get_data(as_text=True)
        assert "fid" not in serialized.casefold()
        assert first_fid not in serialized
        assert rotated_fid not in serialized

    with app.app_context():
        db = get_db()
        devices = list(db.workerPushRegistrations.find({}))
        assert len(devices) == 2
        revoked_first = next(
            item
            for item in devices
            if item["installationId"] == first_installation
        )
        revoked_second = next(
            item
            for item in devices
            if item["installationId"] == second_installation
        )
        assert revoked_first["active"] is False
        assert revoked_first["failureReason"] == "fid_reassigned"
        assert "fid" not in revoked_first
        assert "fidHash" not in revoked_first
        assert revoked_second["active"] is False
        assert revoked_second["failureReason"] == "worker_logout"
        assert "fid" not in revoked_second
        assert "fidHash" not in revoked_second


def test_domain_changes_enqueue_deduplicated_push_jobs(
    app,
    client,
):
    user = client.post(
        "/api/users",
        json={"phone": "+905551112266", "employerKey": "acme"},
    ).get_json()["user"]
    registration = client.put(
        f"/api/users/{user['id']}/devices/"
        "55555555-5555-4555-8555-555555555555",
        json={
            "fid": "domain-events-device-fid-00000001",
            "platform": "android",
            "appVersionCode": 1,
            "appVersionName": "1.0",
        },
    )
    upload = client.post(
        f"/api/users/{user['id']}/videos",
        data={"video": (BytesIO(b"push test"), "push.mp4")},
        content_type="multipart/form-data",
    )
    recommendation = client.get(
        f"/api/users/{user['id']}/dashboard"
    ).get_json()["recommendedJobs"][0]
    application = client.post(
        f"/api/users/{user['id']}/job-applications",
        json={"jobRecommendationId": recommendation["id"]},
    ).get_json()["jobApplication"]
    application_url = (
        "/api/employers/acme/job-applications/"
        f"{application['id']}"
    )
    application_update = client.patch(
        application_url,
        json={"status": "shortlisted"},
    )
    application_replay = client.patch(
        application_url,
        json={"status": "shortlisted"},
    )

    question = client.post(
        f"/api/users/{user['id']}/questions",
        json={"question": "Prim hesaplamamı kim açıklayabilir?"},
    ).get_json()["answer"]
    question_update = client.patch(
        f"/api/employers/acme/questions/{question['id']}",
        json={"answer": "İnsan kaynakları sizinle iletişime geçecek."},
    )
    question_replay = client.patch(
        f"/api/employers/acme/questions/{question['id']}",
        json={"answer": "İnsan kaynakları sizinle iletişime geçecek."},
    )

    shuttle = client.post(
        f"/api/users/{user['id']}/shuttle-requests",
        json={"routeId": "route-1", "pickupNote": "Merkez durak"},
    ).get_json()["shuttleRequest"]
    shuttle_url = (
        "/api/employers/acme/shuttle-requests/"
        f"{shuttle['id']}"
    )
    shuttle_update = client.patch(
        shuttle_url,
        json={"status": "confirmed"},
    )
    shuttle_replay = client.patch(
        shuttle_url,
        json={"status": "confirmed"},
    )

    assert registration.status_code == 200
    assert upload.status_code == 201
    assert application_update.status_code == 200
    assert application_replay.status_code == 200
    assert question["status"] == "pending"
    assert question_update.status_code == 200
    assert question_replay.status_code == 200
    assert shuttle_update.status_code == 200
    assert shuttle_replay.status_code == 200

    with app.app_context():
        db = get_db()
        jobs = list(
            db.pushNotificationJobs.find({}).sort(
                "eventType", 1
            )
        )
        assert [job["eventType"] for job in jobs] == [
            "application_status",
            "question_answered",
            "shuttle_status",
        ]
        assert len({job["eventKey"] for job in jobs}) == 3
        assert all("fid" not in job for job in jobs)
        assert all("fidHash" not in job for job in jobs)

        processed = []
        while True:
            job = claim_push_job(
                db,
                app.config,
                "test-push-worker",
            )
            if job is None:
                break
            processed.append(
                process_claimed_push_job(
                    db,
                    app.config,
                    job,
                )
            )
        assert processed == ["sent", "sent", "sent"]
        assert db.pushNotificationJobs.count_documents(
            {"status": "sent"}
        ) == 3


def test_push_worker_retries_then_revokes_invalid_device(
    app,
    client,
    monkeypatch,
):
    user = client.post(
        "/api/users", json={"phone": "+905551112277"}
    ).get_json()["user"]
    client.put(
        f"/api/users/{user['id']}/devices/"
        "66666666-6666-4666-8666-666666666666",
        json={
            "fid": "retry-device-fid-0000000000001",
            "platform": "android",
            "appVersionCode": 1,
            "appVersionName": "1.0",
        },
    )

    with app.app_context():
        db = get_db()
        enqueue_worker_push(
            db,
            user_id=ObjectId(user["id"]),
            event_key="retry-event",
            event_type="question_answered",
            title="Yanıt",
            body="Sorunuz yanıtlandı.",
            data={"entityId": str(ObjectId())},
        )
        monkeypatch.setattr(
            "app.services.push_notifications.send_push_message",
            lambda *_args, **_kwargs: (
                _raise_error(RuntimeError("temporary"))
            ),
        )
        first_claim = claim_push_job(
            db,
            app.config,
            "retry-worker",
        )
        assert process_claimed_push_job(
            db,
            app.config,
            first_claim,
        ) == "queued"
        db.pushNotificationJobs.update_one(
            {"_id": first_claim["_id"]},
            {"$set": {"availableAt": datetime.now(UTC)}},
        )

        monkeypatch.setattr(
            "app.services.push_notifications.send_push_message",
            lambda *_args, **_kwargs: (
                _raise_error(PermanentDeviceRegistrationError())
            ),
        )
        second_claim = claim_push_job(
            db,
            app.config,
            "retry-worker",
        )
        assert process_claimed_push_job(
            db,
            app.config,
            second_claim,
        ) == "skipped"

        job = db.pushNotificationJobs.find_one(
            {"_id": first_claim["_id"]}
        )
        device = db.workerPushRegistrations.find_one(
            {"userId": ObjectId(user["id"])}
        )
        assert job["status"] == "skipped"
        assert job["attempts"] == 2
        assert job["lastError"] == "invalid_device_registration"
        assert device["active"] is False
        assert "fid" not in device
        assert "fidHash" not in device


def test_worker_push_registration_limits_bound_stored_devices(
    app,
    client,
):
    app.config.update(
        PUSH_MAX_ACTIVE_REGISTRATIONS_PER_WORKER=1,
        PUSH_MAX_STORED_REGISTRATIONS_PER_WORKER=2,
    )
    user = client.post(
        "/api/users", json={"phone": "+905551112299"}
    ).get_json()["user"]

    for index in range(3):
        response = client.put(
            f"/api/users/{user['id']}/devices/"
            f"99999999-9999-4999-8999-99999999999{index}",
            json={
                "fid": f"bounded-device-fid-00000000000{index}",
                "platform": "android",
                "appVersionCode": index + 1,
                "appVersionName": f"1.{index}",
            },
        )
        assert response.status_code == 200

    with app.app_context():
        registrations = list(
            get_db().workerPushRegistrations.find(
                {"userId": ObjectId(user["id"])}
            )
        )
        assert len(registrations) == 2
        active = [
            item for item in registrations if item["active"]
        ]
        assert len(active) == 1
        assert active[0]["appVersionCode"] == 3
        inactive = [
            item for item in registrations if not item["active"]
        ]
        assert inactive[0]["failureReason"] == (
            "active_registration_limit"
        )
        assert inactive[0]["purgeAt"] > inactive[0]["updatedAt"]


def test_push_worker_terminal_failure_degrades_health(
    app,
    client,
    monkeypatch,
):
    app.config["PUSH_JOB_MAX_ATTEMPTS"] = 1
    user = client.post(
        "/api/users", json={"phone": "+905551112288"}
    ).get_json()["user"]
    client.put(
        f"/api/users/{user['id']}/devices/"
        "77777777-7777-4777-8777-777777777777",
        json={
            "fid": "failed-device-fid-00000000001",
            "platform": "android",
            "appVersionCode": 1,
            "appVersionName": "1.0",
        },
    )

    with app.app_context():
        db = get_db()
        enqueue_worker_push(
            db,
            user_id=ObjectId(user["id"]),
            event_key="failed-event",
            event_type="shuttle_status",
            title="Servis",
            body="Servis durumu değişti.",
            data={"entityId": str(ObjectId()), "status": "confirmed"},
        )
        monkeypatch.setattr(
            "app.services.push_notifications.send_push_message",
            lambda *_args, **_kwargs: (
                _raise_error(RuntimeError("provider unavailable"))
            ),
        )
        job = claim_push_job(
            db,
            app.config,
            "failure-worker",
        )
        assert process_claimed_push_job(
            db,
            app.config,
            job,
        ) == "failed"

    health = client.get("/api/health")
    assert health.status_code == 503
    assert health.get_json()["pushNotifications"]["queue"][
        "failed"
    ] == 1


def _raise_error(error: Exception):
    raise error
