from datetime import UTC, datetime

from flask import Blueprint, current_app, jsonify

from app.db import get_client, get_db
from app.services.auth import VALID_STORED_PHONE
from app.services.runtime_dependencies import executable_available


health_bp = Blueprint("health", __name__)


@health_bp.get("/api/live")
def live():
    return jsonify({"status": "ok"})


@health_bp.get("/api/mobile-config")
def mobile_config():
    return jsonify(
        {
            "platform": "android",
            "minSupportedVersionCode": current_app.config.get(
                "MOBILE_MIN_SUPPORTED_VERSION_CODE", 1
            ),
            "latestVersionCode": current_app.config.get(
                "MOBILE_LATEST_VERSION_CODE", 1
            ),
            "maintenanceMode": current_app.config.get(
                "MOBILE_MAINTENANCE_MODE", False
            ),
            "maintenanceMessage": current_app.config.get(
                "MOBILE_MAINTENANCE_MESSAGE", ""
            ),
            "updateMessage": current_app.config.get(
                "MOBILE_UPDATE_MESSAGE", ""
            ),
            "updateUrl": current_app.config.get(
                "MOBILE_UPDATE_URL", ""
            ),
            "privacyPolicyUrl": current_app.config.get(
                "PRIVACY_POLICY_URL", ""
            ),
            "videoConsentVersion": current_app.config.get(
                "VIDEO_CONSENT_VERSION", ""
            ),
        }
    )


@health_bp.get("/api/ready")
def ready():
    get_client().admin.command("ping")
    if (
        current_app.config.get("VIDEO_VALIDATE_CONTENT", True)
        and not executable_available(
            current_app.config.get("FFPROBE_PATH")
        )
    ):
        return (
            jsonify(
                {
                    "status": "degraded",
                    "mongo": "ok",
                    "ffprobe": "unavailable",
                }
            ),
            503,
        )
    return jsonify({"status": "ok", "mongo": "ok"})


@health_bp.get("/api/health")
def health():
    get_client().admin.command("ping")
    db = get_db()
    now = datetime.now(UTC)
    queue = {
        status: db.videoProcessingJobs.count_documents({"status": status})
        for status in ("queued", "processing", "completed", "failed")
    }
    active_video_worker_filter = {
        "status": "running",
        "expiresAt": {"$gt": now},
    }
    active_workers = db.videoWorkerHeartbeats.count_documents(
        active_video_worker_filter
    )
    ready_video_worker_filter = dict(active_video_worker_filter)
    if (
        current_app.config.get("VIDEO_WORKER_WARMUP_MODEL")
        and current_app.config.get("TRANSCRIPTION_PROVIDER")
        == "faster_whisper"
    ):
        ready_video_worker_filter.update(
            {
                "transcriptionProvider": "faster_whisper",
                "modelWarmed": True,
            }
        )
    ready_video_workers = (
        db.videoWorkerHeartbeats.count_documents(
            ready_video_worker_filter
        )
    )
    push_provider = current_app.config.get(
        "PUSH_PROVIDER", "disabled"
    )
    push_queue = {
        status: db.pushNotificationJobs.count_documents(
            {"status": status}
        )
        for status in (
            "queued",
            "processing",
            "sent",
            "failed",
            "skipped",
        )
    }
    active_push_worker_filter = {
        "status": "running",
        "expiresAt": {"$gt": now},
    }
    active_push_workers = db.pushWorkerHeartbeats.count_documents(
        active_push_worker_filter
    )
    ready_push_worker_filter = dict(active_push_worker_filter)
    if (
        push_provider == "fcm"
        and current_app.config.get(
            "PUSH_WORKER_VALIDATE_CREDENTIALS",
            False,
        )
    ):
        ready_push_worker_filter.update(
            {
                "provider": "fcm",
                "projectId": current_app.config.get(
                    "FCM_PROJECT_ID"
                ),
                "credentialsValidated": True,
            }
        )
    ready_push_workers = (
        db.pushWorkerHeartbeats.count_documents(
            ready_push_worker_filter
        )
    )
    source_deletion = {
        "pending": db.videos.count_documents(
            {
                "status": "completed",
                "deleteSourceAfterProcessing": True,
                "storedPath": {"$type": "string"},
                "sourceDeletionStatus": {"$ne": "failed"},
            }
        ),
        "failed": db.videos.count_documents(
            {
                "status": "completed",
                "deleteSourceAfterProcessing": True,
                "sourceDeletionStatus": "failed",
            }
        ),
    }
    idempotency = {
        "processing": db.idempotencyRecords.count_documents(
            {"status": "processing"}
        ),
        "staleProcessing": db.idempotencyRecords.count_documents(
            {
                "status": "processing",
                "expiresAt": {"$lte": now},
            }
        ),
    }
    account_deletion = {
        "pendingFileCleanup": db.accountDeletionRecords.count_documents(
            {"status": "pending_file_cleanup"}
        ),
        "failedFileCleanup": db.accountDeletionRecords.count_documents(
            {"status": "failed"}
        ),
    }
    data_hygiene = {
        "invalidPhoneUsers": db.users.count_documents(
            {"phone": {"$not": VALID_STORED_PHONE}}
        )
    }
    mode = current_app.config.get("VIDEO_PROCESSING_MODE", "thread")
    ffprobe_status = (
        "ok"
        if (
            not current_app.config.get(
                "VIDEO_VALIDATE_CONTENT",
                True,
            )
            or executable_available(
                current_app.config.get("FFPROBE_PATH")
            )
        )
        else "unavailable"
    )
    status = (
        "degraded"
        if (
            (mode == "worker" and ready_video_workers == 0)
            or queue["failed"] > 0
            or (
                push_provider == "fcm"
                and ready_push_workers == 0
            )
            or push_queue["failed"] > 0
            or source_deletion["failed"] > 0
            or idempotency["staleProcessing"] > 0
            or account_deletion["pendingFileCleanup"] > 0
            or account_deletion["failedFileCleanup"] > 0
            or ffprobe_status != "ok"
            or (
                current_app.config.get(
                    "STRICT_DATA_HYGIENE",
                    False,
                )
                and data_hygiene["invalidPhoneUsers"] > 0
            )
        )
        else "ok"
    )
    response = jsonify(
        {
            "status": status,
            "mongo": "ok",
            "videoProcessing": {
                "mode": mode,
                "activeWorkers": active_workers,
                "readyWorkers": ready_video_workers,
                "queue": queue,
            },
            "videoSourceDeletion": source_deletion,
            "pushNotifications": {
                "provider": push_provider,
                "activeWorkers": active_push_workers,
                "readyWorkers": ready_push_workers,
                "queue": push_queue,
            },
            "idempotency": idempotency,
            "accountDeletion": account_deletion,
            "dataHygiene": data_hygiene,
            "runtimeDependencies": {
                "ffprobe": ffprobe_status,
            },
        }
    )
    return response, 503 if status == "degraded" else 200
