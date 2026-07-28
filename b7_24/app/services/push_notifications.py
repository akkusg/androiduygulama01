from __future__ import annotations

import hashlib
import re
import socket
from datetime import UTC, datetime, timedelta
from threading import Event
from uuid import UUID, uuid4

import firebase_admin
import google.auth
from google.auth.credentials import with_scopes_if_required
from google.auth.transport.requests import Request as GoogleAuthRequest
from firebase_admin import exceptions as firebase_exceptions
from firebase_admin import messaging
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from werkzeug.exceptions import BadRequest

from app.db import ensure_indexes, get_db


PUSH_EVENT_TYPES = {
    "application_status",
    "question_answered",
    "shuttle_status",
}


VALID_FIREBASE_INSTALLATION_ID = re.compile(
    r"^[A-Za-z0-9_-]{10,256}$"
)


class PermanentDeviceRegistrationError(Exception):
    pass


def register_worker_device(
    db,
    user: dict,
    installation_id: str,
    payload: dict,
    config=None,
) -> dict:
    normalized_installation_id = _installation_id(installation_id)
    if not isinstance(payload, dict):
        raise BadRequest("Request body must be a JSON object")
    allowed_fields = {
        "fid",
        "platform",
        "appVersionCode",
        "appVersionName",
    }
    unknown_fields = set(payload) - allowed_fields
    if unknown_fields:
        raise BadRequest(
            "Unknown device fields: "
            + ", ".join(sorted(unknown_fields))
        )

    fid = payload.get("fid")
    if not isinstance(fid, str):
        raise BadRequest("fid must be a string")
    fid = fid.strip()
    if not VALID_FIREBASE_INSTALLATION_ID.fullmatch(fid):
        raise BadRequest("fid is not a valid Firebase installation id")

    platform = payload.get("platform", "android")
    if platform != "android":
        raise BadRequest("platform must be android")
    version_code = payload.get("appVersionCode")
    if (
        isinstance(version_code, bool)
        or not isinstance(version_code, int)
        or not 1 <= version_code <= 2_100_000_000
    ):
        raise BadRequest("appVersionCode must be a positive integer")
    version_name = payload.get("appVersionName")
    if not isinstance(version_name, str):
        raise BadRequest("appVersionName must be a string")
    version_name = version_name.strip()
    if not 1 <= len(version_name) <= 80:
        raise BadRequest(
            "appVersionName must contain between 1 and 80 characters"
        )

    fid_hash = hashlib.sha256(fid.encode("utf-8")).hexdigest()
    employer_key = user.get("employerKey") or "default"
    now = datetime.now(UTC)
    selector = {
        "userId": user["_id"],
        "installationId": normalized_installation_id,
    }
    update = {
        "$set": {
            "employerKey": employer_key,
            "fid": fid,
            "fidHash": fid_hash,
            "platform": platform,
            "appVersionCode": version_code,
            "appVersionName": version_name,
            "active": True,
            "lastSeenAt": now,
            "updatedAt": now,
        },
        "$unset": {
            "revokedAt": "",
            "failureReason": "",
            "purgeAt": "",
        },
        "$setOnInsert": {"createdAt": now},
    }

    competing = db.workerPushRegistrations.find_one(
        {
            "fidHash": fid_hash,
            "$or": [
                {"userId": {"$ne": user["_id"]}},
                {"installationId": {"$ne": normalized_installation_id}},
            ],
        },
        {"_id": 1},
    )
    if competing:
        _revoke_device_record(
            db,
            competing["_id"],
            "fid_reassigned",
            now,
        )
    try:
        db.workerPushRegistrations.update_one(
            selector,
            update,
            upsert=True,
        )
    except DuplicateKeyError:
        competing = db.workerPushRegistrations.find_one(
            {"fidHash": fid_hash},
            {"_id": 1},
        )
        if competing:
            _revoke_device_record(
                db,
                competing["_id"],
                "fid_reassigned",
                now,
            )
        db.workerPushRegistrations.update_one(
            selector,
            update,
            upsert=True,
        )
    device = db.workerPushRegistrations.find_one(selector)
    _enforce_worker_registration_limits(
        db,
        user["_id"],
        device["_id"],
        config or {},
        now,
    )
    return db.workerPushRegistrations.find_one(selector)


def unregister_worker_device(
    db,
    user: dict,
    installation_id: str,
) -> bool:
    normalized_installation_id = _installation_id(installation_id)
    device = db.workerPushRegistrations.find_one(
        {
            "userId": user["_id"],
            "installationId": normalized_installation_id,
            "active": True,
        },
        {"_id": 1},
    )
    if device is None:
        return False
    _revoke_device_record(
        db,
        device["_id"],
        "worker_logout",
        datetime.now(UTC),
    )
    return True


def serialize_worker_device(device: dict) -> dict:
    return {
        "id": str(device["_id"]),
        "installationId": device.get("installationId"),
        "platform": device.get("platform"),
        "appVersionCode": device.get("appVersionCode"),
        "appVersionName": device.get("appVersionName"),
        "active": device.get("active", False),
        "lastSeenAt": _isoformat(device.get("lastSeenAt")),
    }


def enqueue_worker_push(
    db,
    *,
    user_id,
    event_key: str,
    event_type: str,
    title: str,
    body: str,
    data: dict[str, str],
    event_ttl_seconds: int = 7 * 24 * 60 * 60,
) -> int:
    if event_type not in PUSH_EVENT_TYPES:
        raise ValueError("Unsupported push event type")
    event_key = _bounded_text(event_key, "event_key", 256)
    title = _bounded_text(title, "title", 160)
    body = _bounded_text(body, "body", 500)
    normalized_data = _normalize_push_data(data)
    normalized_data.update(
        {
            "eventId": event_key,
            "eventType": event_type,
            "title": title,
            "body": body,
        }
    )

    now = datetime.now(UTC)
    expires_at = now + timedelta(seconds=event_ttl_seconds)
    devices = list(
        db.workerPushRegistrations.find(
            {
                "userId": user_id,
                "active": True,
                "platform": "android",
            },
            {"_id": 1},
        )
    )
    queued = 0
    for device in devices:
        result = db.pushNotificationJobs.update_one(
            {
                "eventKey": event_key,
                "deviceRegistrationId": device["_id"],
            },
            {
                "$setOnInsert": {
                    "userId": user_id,
                    "deviceRegistrationId": device["_id"],
                    "eventKey": event_key,
                    "eventType": event_type,
                    "title": title,
                    "body": body,
                    "data": normalized_data,
                    "status": "queued",
                    "attempts": 0,
                    "availableAt": now,
                    "expiresAt": expires_at,
                    "createdAt": now,
                    "updatedAt": now,
                }
            },
            upsert=True,
        )
        queued += int(result.upserted_id is not None)
    return queued


def enqueue_application_status_push(
    db,
    application: dict,
    event_id: str,
    *,
    title: str | None = None,
    body: str | None = None,
) -> int:
    job = application.get("job") or {}
    job_title = job.get("title") or "İş başvurunuz"
    status = application.get("status") or ""
    return enqueue_worker_push(
        db,
        user_id=application["userId"],
        event_key=f"application:{application['_id']}:{event_id}",
        event_type="application_status",
        title=title or "Başvuru durumunuz güncellendi",
        body=body
        or f"{job_title}: {_application_status_label(status)}",
        data={
            "entityId": str(application["_id"]),
            "status": status,
        },
    )


def enqueue_question_answered_push(
    db,
    question: dict,
    event_id: str,
) -> int:
    return enqueue_worker_push(
        db,
        user_id=question["userId"],
        event_key=f"question:{question['_id']}:{event_id}",
        event_type="question_answered",
        title="Sorunuz yanıtlandı",
        body="İşveren yanıtını uygulamada görebilirsiniz.",
        data={
            "entityId": str(question["_id"]),
            "status": "answered",
        },
    )


def enqueue_shuttle_status_push(
    db,
    shuttle_request: dict,
    event_id: str,
) -> int:
    route_name = (
        shuttle_request.get("routeName")
        or "Servis talebiniz"
    )
    status = shuttle_request.get("status") or ""
    return enqueue_worker_push(
        db,
        user_id=shuttle_request["userId"],
        event_key=f"shuttle:{shuttle_request['_id']}:{event_id}",
        event_type="shuttle_status",
        title="Servis durumunuz güncellendi",
        body=f"{route_name}: {_shuttle_status_label(status)}",
        data={
            "entityId": str(shuttle_request["_id"]),
            "status": status,
            "routeName": route_name,
        },
    )


def claim_push_job(
    db,
    config,
    worker_id: str,
    now: datetime | None = None,
) -> dict | None:
    claimed_at = now or datetime.now(UTC)
    maximum_attempts = config.get("PUSH_JOB_MAX_ATTEMPTS", 5)
    lease_seconds = config.get("PUSH_JOB_LEASE_SECONDS", 60)
    return db.pushNotificationJobs.find_one_and_update(
        {
            "attempts": {"$lt": maximum_attempts},
            "availableAt": {"$lte": claimed_at},
            "expiresAt": {"$gt": claimed_at},
            "$or": [
                {"status": "queued"},
                {
                    "status": "processing",
                    "lockUntil": {"$lte": claimed_at},
                },
            ],
        },
        {
            "$set": {
                "status": "processing",
                "lockedBy": worker_id,
                "lockUntil": claimed_at
                + timedelta(seconds=lease_seconds),
                "updatedAt": claimed_at,
            },
            "$inc": {"attempts": 1},
            "$unset": {"lastError": ""},
        },
        sort=[("availableAt", 1), ("createdAt", 1)],
        return_document=ReturnDocument.AFTER,
    )


def process_claimed_push_job(
    db,
    config,
    job: dict,
) -> str:
    now = datetime.now(UTC)
    lock_query = {
        "_id": job["_id"],
        "status": "processing",
        "lockedBy": job.get("lockedBy"),
    }
    device = db.workerPushRegistrations.find_one(
        {
            "_id": job.get("deviceRegistrationId"),
            "userId": job.get("userId"),
            "active": True,
        }
    )
    if device is None:
        _finish_push_job(
            db,
            lock_query,
            "skipped",
            now,
            config,
            error_code="device_inactive",
        )
        return "skipped"

    try:
        message_id = send_push_message(
            config,
            device["fid"],
            job.get("data") or {},
        )
    except PermanentDeviceRegistrationError:
        _finish_push_job(
            db,
            lock_query,
            "skipped",
            now,
            config,
            error_code="invalid_device_registration",
        )
        _revoke_device_record(
            db,
            device["_id"],
            "provider_rejected_registration",
            now,
        )
        return "skipped"
    except Exception as error:
        return _retry_or_fail_push_job(
            db,
            lock_query,
            job,
            config,
            now,
            type(error).__name__,
        )

    db.pushNotificationJobs.update_one(
        lock_query,
        {
            "$set": {
                "status": "sent",
                "providerMessageId": message_id,
                "sentAt": now,
                "updatedAt": now,
                "purgeAt": now
                + timedelta(
                    seconds=config.get(
                        "PUSH_JOB_RETENTION_SECONDS",
                        7 * 24 * 60 * 60,
                    )
                ),
            },
            "$unset": {
                "lockedBy": "",
                "lockUntil": "",
                "lastError": "",
            },
        },
    )
    return "sent"


def send_push_message(
    config,
    fid: str,
    data: dict[str, str],
) -> str:
    provider = config.get("PUSH_PROVIDER", "disabled").lower()
    if provider == "static":
        return f"static-{uuid4().hex}"
    if provider != "fcm":
        raise RuntimeError("Push provider is not configured")

    firebase_app = initialize_push_provider(config)
    message = messaging.Message(
        fid=fid,
        data=data,
        android=messaging.AndroidConfig(
            priority="high",
            ttl=timedelta(hours=24),
        ),
    )
    try:
        return messaging.send(message, app=firebase_app)
    except (
        messaging.UnregisteredError,
        firebase_exceptions.InvalidArgumentError,
    ) as error:
        raise PermanentDeviceRegistrationError() from error


def initialize_push_provider(config):
    provider = config.get("PUSH_PROVIDER", "disabled").lower()
    if provider in {"disabled", "static"}:
        return None
    if provider != "fcm":
        raise RuntimeError("Unsupported push provider")

    project_id = config.get("FCM_PROJECT_ID", "")
    if not project_id:
        raise RuntimeError("FCM_PROJECT_ID is not configured")
    app_name = f"y724-{project_id}"
    try:
        return firebase_admin.get_app(app_name)
    except ValueError:
        credentials, detected_project_id = google.auth.default()
        if (
            detected_project_id
            and detected_project_id != project_id
        ):
            raise RuntimeError(
                "Firebase credential project does not match "
                "FCM_PROJECT_ID"
            )
        if config.get(
            "PUSH_WORKER_VALIDATE_CREDENTIALS",
            False,
        ):
            credentials = with_scopes_if_required(
                credentials,
                [
                    "https://www.googleapis.com/auth/"
                    "firebase.messaging"
                ],
            )
            credentials.refresh(GoogleAuthRequest())
        return firebase_admin.initialize_app(
            credential=credentials,
            options={"projectId": project_id},
            name=app_name,
        )


def run_push_worker(app, stop_event: Event | None = None) -> None:
    stop = stop_event or Event()
    worker_id = _worker_identity()
    poll_seconds = app.config.get("PUSH_WORKER_POLL_SECONDS", 2)
    heartbeat_seconds = app.config.get(
        "PUSH_WORKER_HEARTBEAT_SECONDS", 10
    )
    started_at = datetime.now(UTC)
    last_cleanup_at: datetime | None = None

    with app.app_context():
        ensure_indexes()
        runtime_info = prepare_push_worker_runtime(app.config)
        app.logger.info("Push worker started: %s", worker_id)
        while not stop.is_set():
            now = datetime.now(UTC)
            _record_push_worker_heartbeat(
                get_db(),
                worker_id,
                started_at,
                now,
                heartbeat_seconds,
                runtime_info,
            )
            if (
                last_cleanup_at is None
                or (now - last_cleanup_at).total_seconds() >= 3600
            ):
                deactivate_stale_devices(get_db(), app.config, now)
                _skip_expired_push_jobs(get_db(), app.config, now)
                last_cleanup_at = now
            job = claim_push_job(
                get_db(),
                app.config,
                worker_id,
                now,
            )
            if job:
                process_claimed_push_job(
                    get_db(),
                    app.config,
                    job,
                )
                continue
            stop.wait(poll_seconds)

        get_db().pushWorkerHeartbeats.update_one(
            {"_id": worker_id},
            {
                "$set": {
                    "status": "stopped",
                    "stoppedAt": datetime.now(UTC),
                    "updatedAt": datetime.now(UTC),
                }
            },
        )
        app.logger.info("Push worker stopped: %s", worker_id)


def prepare_push_worker_runtime(config) -> dict:
    provider = config.get("PUSH_PROVIDER", "disabled").lower()
    initialize_push_provider(config)
    return {
        "provider": provider,
        "projectId": config.get("FCM_PROJECT_ID") or None,
        "credentialsValidated": (
            provider == "fcm"
            and config.get(
                "PUSH_WORKER_VALIDATE_CREDENTIALS",
                False,
            )
        ),
    }


def deactivate_stale_devices(
    db,
    config,
    now: datetime | None = None,
) -> int:
    checked_at = now or datetime.now(UTC)
    retention_days = config.get(
        "PUSH_REGISTRATION_RETENTION_DAYS",
        90,
    )
    result = db.workerPushRegistrations.update_many(
        {
            "active": True,
            "lastSeenAt": {
                "$lte": checked_at - timedelta(days=retention_days)
            },
        },
        {
            "$set": {
                "active": False,
                "failureReason": "stale",
                "revokedAt": checked_at,
                "updatedAt": checked_at,
                "purgeAt": checked_at
                + timedelta(days=retention_days),
            }
        },
    )
    return result.modified_count


def _revoke_device_record(
    db,
    device_id,
    reason: str,
    now: datetime,
    retention_days: int = 90,
) -> None:
    db.workerPushRegistrations.update_one(
        {"_id": device_id},
        {
            "$set": {
                "active": False,
                "failureReason": reason,
                "revokedAt": now,
                "updatedAt": now,
                "purgeAt": now + timedelta(days=retention_days),
            },
            "$unset": {
                "fid": "",
                "fidHash": "",
            },
        },
    )
    db.pushNotificationJobs.update_many(
        {
            "deviceRegistrationId": device_id,
            "status": {"$in": ["queued", "processing"]},
        },
        {
            "$set": {
                "status": "skipped",
                "lastError": "device_inactive",
                "updatedAt": now,
                "purgeAt": now + timedelta(days=7),
            },
            "$unset": {
                "lockedBy": "",
                "lockUntil": "",
            },
        },
    )


def _enforce_worker_registration_limits(
    db,
    user_id,
    current_registration_id,
    config,
    now: datetime,
) -> None:
    active_limit = config.get(
        "PUSH_MAX_ACTIVE_REGISTRATIONS_PER_WORKER",
        5,
    )
    stored_limit = config.get(
        "PUSH_MAX_STORED_REGISTRATIONS_PER_WORKER",
        20,
    )
    retention_days = config.get(
        "PUSH_REGISTRATION_RETENTION_DAYS",
        90,
    )
    excess_active = list(
        db.workerPushRegistrations.find(
            {
                "userId": user_id,
                "active": True,
            },
            {"_id": 1},
        )
        .sort([("lastSeenAt", -1), ("_id", -1)])
        .skip(active_limit)
    )
    for registration in excess_active:
        _revoke_device_record(
            db,
            registration["_id"],
            "active_registration_limit",
            now,
            retention_days,
        )

    excess_count = max(
        0,
        db.workerPushRegistrations.count_documents(
            {"userId": user_id}
        )
        - stored_limit,
    )
    if excess_count == 0:
        return
    removable = list(
        db.workerPushRegistrations.find(
            {
                "userId": user_id,
                "active": False,
                "_id": {"$ne": current_registration_id},
            },
            {"_id": 1},
        )
        .sort([("updatedAt", 1), ("_id", 1)])
        .limit(excess_count)
    )
    if removable:
        db.workerPushRegistrations.delete_many(
            {
                "_id": {
                    "$in": [item["_id"] for item in removable]
                }
            }
        )


def _retry_or_fail_push_job(
    db,
    lock_query: dict,
    job: dict,
    config,
    now: datetime,
    error_code: str,
) -> str:
    attempts = job.get("attempts", 0)
    maximum_attempts = config.get("PUSH_JOB_MAX_ATTEMPTS", 5)
    if attempts >= maximum_attempts:
        _finish_push_job(
            db,
            lock_query,
            "failed",
            now,
            config,
            error_code=error_code,
        )
        return "failed"

    base_seconds = config.get("PUSH_JOB_RETRY_BASE_SECONDS", 15)
    maximum_seconds = config.get("PUSH_JOB_RETRY_MAX_SECONDS", 900)
    delay_seconds = min(
        maximum_seconds,
        base_seconds * (2 ** max(0, attempts - 1)),
    )
    db.pushNotificationJobs.update_one(
        lock_query,
        {
            "$set": {
                "status": "queued",
                "availableAt": now + timedelta(seconds=delay_seconds),
                "lastError": error_code[:160],
                "updatedAt": now,
            },
            "$unset": {
                "lockedBy": "",
                "lockUntil": "",
            },
        },
    )
    return "queued"


def _finish_push_job(
    db,
    lock_query: dict,
    status: str,
    now: datetime,
    config,
    error_code: str,
) -> None:
    db.pushNotificationJobs.update_one(
        lock_query,
        {
            "$set": {
                "status": status,
                "lastError": error_code[:160],
                "updatedAt": now,
                "purgeAt": now
                + timedelta(
                    seconds=config.get(
                        "PUSH_JOB_RETENTION_SECONDS",
                        7 * 24 * 60 * 60,
                    )
                ),
            },
            "$unset": {
                "lockedBy": "",
                "lockUntil": "",
            },
        },
    )


def _skip_expired_push_jobs(db, config, now: datetime) -> int:
    result = db.pushNotificationJobs.update_many(
        {
            "status": {"$in": ["queued", "processing"]},
            "expiresAt": {"$lte": now},
        },
        {
            "$set": {
                "status": "skipped",
                "lastError": "event_expired",
                "updatedAt": now,
                "purgeAt": now
                + timedelta(
                    seconds=config.get(
                        "PUSH_JOB_RETENTION_SECONDS",
                        7 * 24 * 60 * 60,
                    )
                ),
            },
            "$unset": {
                "lockedBy": "",
                "lockUntil": "",
            },
        },
    )
    return result.modified_count


def _record_push_worker_heartbeat(
    db,
    worker_id: str,
    started_at: datetime,
    now: datetime,
    heartbeat_seconds: int,
    runtime_info: dict,
) -> None:
    db.pushWorkerHeartbeats.update_one(
        {"_id": worker_id},
        {
            "$set": {
                "host": socket.gethostname(),
                "pid": _process_id(),
                "status": "running",
                **runtime_info,
                "startedAt": started_at,
                "updatedAt": now,
                "expiresAt": now
                + timedelta(seconds=max(heartbeat_seconds * 3, 30)),
            }
        },
        upsert=True,
    )


def _installation_id(value: str) -> str:
    if not isinstance(value, str):
        raise BadRequest("Invalid installation id")
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError):
        raise BadRequest("Invalid installation id") from None
    if str(parsed) != value.casefold():
        raise BadRequest("Invalid installation id")
    return str(parsed)


def _normalize_push_data(data: dict[str, str]) -> dict[str, str]:
    if not isinstance(data, dict) or len(data) > 20:
        raise ValueError("Push data must be an object with at most 20 items")
    normalized = {}
    for key, value in data.items():
        if (
            not isinstance(key, str)
            or not isinstance(value, str)
            or not key
            or len(key) > 64
            or len(value) > 500
        ):
            raise ValueError("Push data contains an invalid key or value")
        normalized[key] = value
    return normalized


def _bounded_text(value: str, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    value = value.strip()
    if len(value) > maximum:
        raise ValueError(f"{field} cannot exceed {maximum} characters")
    return value


def _application_status_label(status: str) -> str:
    return {
        "submitted": "Başvuru alındı",
        "reviewing": "İncelemede",
        "shortlisted": "Ön listeye alındı",
        "rejected": "Reddedildi",
        "hired": "İşe alındınız",
    }.get(status, "Durum değişti")


def _shuttle_status_label(status: str) -> str:
    return {
        "confirmed": "Onaylandı",
        "rejected": "Reddedildi",
        "completed": "Tamamlandı",
    }.get(status, "Durum değişti")


def _worker_identity() -> str:
    return f"{socket.gethostname()}:{_process_id()}:{uuid4().hex[:8]}"


def _process_id() -> int:
    import os

    return os.getpid()


def _isoformat(value) -> str | None:
    return value.isoformat() if value else None
