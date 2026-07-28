from __future__ import annotations

import hashlib
import os
import re
import socket
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Thread
from uuid import uuid4

from bson import ObjectId
from flask import Flask, current_app
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from werkzeug.exceptions import Conflict, NotFound

from app.db import ensure_indexes, get_db
from app.services.transcription import (
    transcribe_video,
    warm_up_transcription_provider,
)
from app.services.account_deletion import (
    account_deletion_requested,
    cleanup_account_deletion_files,
    purge_worker_processing_derivatives,
)


JOB_TEMPLATES = [
    {
        "key": "field-operations",
        "title": "Saha Operasyon Görevlisi",
        "company": "Yedi Yirmi Dört Operasyon",
        "location": "İstanbul",
        "requiredSkills": ["saha operasyonu", "iletişim", "vardiya uyumu"],
        "baseScore": 82,
    },
    {
        "key": "warehouse-logistics",
        "title": "Depo ve Lojistik Personeli",
        "company": "Yedi Yirmi Dört Lojistik",
        "location": "İstanbul",
        "requiredSkills": ["lojistik", "dikkat", "takım çalışması"],
        "baseScore": 78,
    },
    {
        "key": "technical-support",
        "title": "Teknik Destek Elemanı",
        "company": "Yedi Yirmi Dört Teknik",
        "location": "Kocaeli",
        "requiredSkills": ["teknik destek", "problem çözme", "müşteri iletişimi"],
        "baseScore": 74,
    },
    {
        "key": "maintenance-repair",
        "title": "Bakım Onarım Teknisyeni",
        "company": "Yedi Yirmi Dört Teknik Servis",
        "location": "İstanbul",
        "requiredSkills": ["bakım onarım", "elektrik", "tesisatçılık"],
        "baseScore": 76,
    },
    {
        "key": "welder",
        "title": "Kaynak Ustası",
        "company": "Yedi Yirmi Dört Üretim",
        "location": "Kocaeli",
        "requiredSkills": ["kaynak", "iş güvenliği", "teknik beceri"],
        "baseScore": 80,
    },
]

SKILL_KEYWORDS = {
    "araç kullanma": {"araç", "araba", "şoför", "sofor", "sürücü", "surucu", "ehliyet", "driver"},
    "bakım onarım": {"bakım", "onarım", "tamir", "servis", "montaj"},
    "depo": {"depo", "stok", "paketleme", "sevkiyat"},
    "elektrik": {"elektrik", "elektrikçi", "elektrikci", "kablo", "pano"},
    "iletişim": {"iletişim", "iletisim", "müşteri", "musteri", "ekip", "takım", "takim"},
    "iş güvenliği": {
        "güvenlik",
        "güvenliğ",
        "guvenlik",
        "guvenlig",
        "isg",
        "baret",
        "emniyet",
    },
    "kaynak": {"kaynak", "kaynakçı", "kaynakci", "welder"},
    "lojistik": {"lojistik", "kurye", "dağıtım", "dagitim", "teslimat", "nakliye"},
    "müşteri iletişimi": {"müşteri", "musteri", "servis", "destek", "çağrı", "cagri"},
    "problem çözme": {"problem", "çözüm", "cozum", "arıza", "ariza", "hata"},
    "satış": {"satış", "satis", "pazarlama", "ikna"},
    "takım çalışması": {"takım", "takim", "ekip", "uyum"},
    "teknik beceri": {"teknik", "usta", "ustalık", "ustalik", "beceri"},
    "teknik destek": {"teknik", "destek", "servis", "arıza", "ariza"},
    "tesisatçılık": {"tesisat", "tesisatçı", "tesisatci", "su", "boru"},
    "vardiya uyumu": {"vardiya", "gece", "esnek", "müsait", "musait", "hafta sonu"},
}


def enqueue_video_processing(app: Flask, video_id: ObjectId) -> None:
    if app.config.get("VIDEO_PROCESSING_INLINE"):
        with app.app_context():
            process_video(video_id)
        return

    if app.config.get("VIDEO_PROCESSING_MODE", "thread") == "worker":
        return

    worker = Thread(
        target=_process_video_with_context,
        args=(app, video_id),
        name=f"video-processing-{video_id}",
        daemon=True,
    )
    worker.start()


def _process_video_with_context(app: Flask, video_id: ObjectId) -> None:
    with app.app_context():
        process_video(video_id)


def create_processing_job(db, video: dict, max_attempts: int) -> dict:
    now = datetime.now(UTC)
    job = db.videoProcessingJobs.find_one({"videoId": video["_id"]})
    if job:
        return job

    document = {
        "videoId": video["_id"],
        "userId": video["userId"],
        "status": "queued",
        "attempts": 0,
        "maxAttempts": max_attempts,
        "availableAt": now,
        "createdAt": now,
        "updatedAt": now,
    }
    try:
        result = db.videoProcessingJobs.insert_one(document)
        document["_id"] = result.inserted_id
        return document
    except DuplicateKeyError:
        return db.videoProcessingJobs.find_one({"videoId": video["_id"]})


def requeue_failed_video_job(
    db,
    job: dict,
    config,
    *,
    requested_by: str,
) -> dict:
    if job.get("status") != "failed":
        raise Conflict("Only failed video processing jobs can be retried")

    user = db.users.find_one({"_id": job.get("userId")})
    video = db.videos.find_one(
        {
            "_id": job.get("videoId"),
            "userId": job.get("userId"),
        }
    )
    if user is None or video is None:
        raise NotFound("Video processing job owner or video not found")
    if user.get("latestVideoId") != video["_id"]:
        raise Conflict("Only the worker's current video can be retried")

    stored_path = video.get("storedPath")
    if (
        not isinstance(stored_path, str)
        or not Path(stored_path).is_file()
    ):
        raise Conflict(
            "The source video is unavailable; the worker must upload a new video"
        )

    now = datetime.now(UTC)
    result = db.videoProcessingJobs.update_one(
        {
            "_id": job["_id"],
            "status": "failed",
        },
        {
            "$set": {
                "status": "queued",
                "attempts": 0,
                "maxAttempts": config.get(
                    "VIDEO_JOB_MAX_ATTEMPTS",
                    3,
                ),
                "availableAt": now,
                "manualRetriedAt": now,
                "manualRetriedBy": requested_by[:160],
                "updatedAt": now,
            },
            "$push": {
                "manualRetryHistory": {
                    "requestedAt": now,
                    "requestedBy": requested_by[:160],
                    "previousError": str(
                        job.get("lastError") or ""
                    )[:2000],
                    "previousAttempts": job.get("attempts", 0),
                }
            },
            "$unset": {
                "failedAt": "",
                "lastFailedAt": "",
                "lastError": "",
                "lockedAt": "",
                "lockedBy": "",
                "lockToken": "",
                "leaseExpiresAt": "",
                "purgeAt": "",
            },
            "$inc": {"manualRetryCount": 1},
        },
    )
    if result.modified_count != 1:
        raise Conflict("Video processing job status changed")

    db.videos.update_one(
        {"_id": video["_id"]},
        {
            "$set": {
                "status": "processing",
                "updatedAt": now,
            },
            "$unset": {
                "processingError": "",
                "nextRetryAt": "",
            },
        },
    )
    db.users.update_one(
        {
            "_id": user["_id"],
            "latestVideoId": video["_id"],
        },
        {
            "$set": {
                "profileStatus": "video_processing",
                "videoStatus": "processing",
                "updatedAt": now,
            }
        },
    )
    return db.videoProcessingJobs.find_one({"_id": job["_id"]})


def claim_video_job(
    db,
    config,
    *,
    video_id: ObjectId | None = None,
    worker_id: str | None = None,
) -> dict | None:
    now = datetime.now(UTC)
    max_attempts = config.get("VIDEO_JOB_MAX_ATTEMPTS", 3)
    lease_seconds = config.get("VIDEO_JOB_LEASE_SECONDS", 900)
    eligibility = {
        "$and": [
            {
                "$or": [
                    {
                        "status": "queued",
                        "$or": [
                            {"availableAt": {"$lte": now}},
                            {"availableAt": {"$exists": False}},
                        ],
                    },
                    {
                        "status": "processing",
                        "leaseExpiresAt": {"$lte": now},
                    },
                ]
            },
            {
                "$expr": {
                    "$lt": [
                        {"$ifNull": ["$attempts", 0]},
                        {"$ifNull": ["$maxAttempts", max_attempts]},
                    ]
                }
            },
        ]
    }
    if video_id is not None:
        eligibility["$and"].append({"videoId": video_id})

    lock_token = uuid4().hex
    return db.videoProcessingJobs.find_one_and_update(
        eligibility,
        {
            "$set": {
                "status": "processing",
                "lockedAt": now,
                "lockedBy": worker_id or _worker_identity(),
                "lockToken": lock_token,
                "leaseExpiresAt": now + timedelta(seconds=lease_seconds),
                "startedAt": now,
                "updatedAt": now,
            },
            "$unset": {"purgeAt": ""},
            "$inc": {"attempts": 1},
        },
        sort=[("availableAt", 1), ("createdAt", 1)],
        return_document=ReturnDocument.AFTER,
    )


def process_video(video_id: ObjectId) -> bool:
    db = get_db()
    video = db.videos.find_one({"_id": video_id})
    if video is None:
        return False
    create_processing_job(
        db,
        video,
        current_app.config.get("VIDEO_JOB_MAX_ATTEMPTS", 3),
    )
    job = claim_video_job(
        db, current_app.config, video_id=video_id
    )
    if job is None:
        return False
    process_claimed_video_job(job)
    return True


def process_claimed_video_job(job: dict) -> None:
    db = get_db()
    video_id = job["videoId"]
    lock_query = {"_id": job["_id"], "lockToken": job["lockToken"]}
    if account_deletion_requested(db, job["userId"]):
        _cancel_deleted_account_job(
            db,
            lock_query,
            job["userId"],
        )
        return
    video = db.videos.find_one({"_id": video_id})
    user = (
        db.users.find_one({"_id": video["userId"]})
        if video is not None
        else None
    )
    if video is None or user is None:
        _fail_claimed_job(
            db,
            job,
            lock_query,
            RuntimeError("Video or user record not found"),
            retryable=False,
        )
        return

    started_at = datetime.now(UTC)

    try:
        db.videoProcessingJobs.update_one(
            lock_query,
            {"$set": {"updatedAt": started_at}},
        )
        db.videos.update_one(
            {"_id": video_id},
            {
                "$set": {
                    "status": "processing",
                    "processingStartedAt": started_at,
                    "updatedAt": started_at,
                },
                "$unset": {"processingError": ""},
            },
        )

        with _JobLeaseHeartbeat(
            db,
            lock_query,
            current_app.config.get("VIDEO_JOB_LEASE_SECONDS", 900),
            current_app.config.get("VIDEO_JOB_HEARTBEAT_SECONDS", 60),
        ):
            transcript = transcribe_video(video)
            if account_deletion_requested(db, user["_id"]):
                _cancel_deleted_account_job(
                    db,
                    lock_query,
                    user["_id"],
                )
                return
            _store_transcript(db, video, transcript)
            if account_deletion_requested(db, user["_id"]):
                _cancel_deleted_account_job(
                    db,
                    lock_query,
                    user["_id"],
                )
                return
            analysis = analyze_video(video, transcript)
            latest_user = db.users.find_one(
                {
                    "_id": user["_id"],
                    "latestVideoId": video_id,
                }
            )
            if latest_user is not None:
                profile = build_candidate_profile(
                    latest_user, video, analysis, started_at
                )
                existing_profile = db.candidateProfiles.find_one(
                    {"userId": user["_id"]}
                )
                if (
                    existing_profile
                    and existing_profile.get("createdAt")
                ):
                    profile["createdAt"] = existing_profile[
                        "createdAt"
                    ]
                db.candidateProfiles.replace_one(
                    {"userId": user["_id"]},
                    profile,
                    upsert=True,
                )
                refresh_user_job_recommendations(
                    db,
                    latest_user,
                    video,
                    profile,
                    started_at,
                )
                if account_deletion_requested(db, user["_id"]):
                    _cancel_deleted_account_job(
                        db,
                        lock_query,
                        user["_id"],
                    )
                    return

        completed_at = datetime.now(UTC)
        if db.videoProcessingJobs.find_one(lock_query) is None:
            current_app.logger.warning(
                "Video job lease lost before completion for %s", video_id
            )
            return

        db.videos.update_one(
            {"_id": video_id},
            {
                "$set": {
                    "status": "completed",
                    "analysis": analysis,
                    "processingCompletedAt": completed_at,
                    "updatedAt": completed_at,
                }
            },
        )
        db.users.update_one(
            {
                "_id": user["_id"],
                "latestVideoId": video_id,
            },
            {
                "$set": {
                    **_candidate_name_update(
                        analysis,
                        latest_user or user,
                    ),
                    "profileStatus": "profile_ready",
                    "videoStatus": "completed",
                    "updatedAt": completed_at,
                }
            },
        )
        db.videoProcessingJobs.update_one(
            lock_query,
            {
                "$set": {
                    "status": "completed",
                    "completedAt": completed_at,
                    "purgeAt": _video_job_purge_at(
                        completed_at,
                        current_app.config,
                    ),
                    "updatedAt": completed_at,
                },
                "$unset": {
                    "lockedAt": "",
                    "lockedBy": "",
                    "lockToken": "",
                    "leaseExpiresAt": "",
                    "lastError": "",
                },
            },
        )
        if video.get("deleteSourceAfterProcessing") is True:
            _delete_processed_video_source(db, video)
    except Exception as error:
        current_app.logger.exception("Video processing failed for %s", video_id)
        _fail_claimed_job(db, job, lock_query, error, retryable=True)


def _cancel_deleted_account_job(
    db,
    lock_query: dict,
    user_id: ObjectId,
) -> None:
    db.videoProcessingJobs.delete_one(lock_query)
    purge_worker_processing_derivatives(db, user_id)


def run_video_worker(app: Flask, stop_event: Event | None = None) -> None:
    stop = stop_event or Event()
    worker_id = _worker_identity()
    poll_seconds = app.config.get("VIDEO_WORKER_POLL_SECONDS", 2)
    heartbeat_seconds = app.config.get(
        "VIDEO_WORKER_HEARTBEAT_SECONDS", 10
    )
    started_at = datetime.now(UTC)
    last_source_cleanup_at: datetime | None = None

    with app.app_context():
        ensure_indexes()
        runtime_info = prepare_video_worker_runtime(app.config)
        app.logger.info("Video worker started: %s", worker_id)
        while not stop.is_set():
            now = datetime.now(UTC)
            _record_worker_heartbeat(
                get_db(),
                worker_id,
                started_at,
                now,
                heartbeat_seconds,
                runtime_info,
            )
            if (
                last_source_cleanup_at is None
                or (now - last_source_cleanup_at).total_seconds() >= 60
            ):
                cleanup_pending_video_sources(get_db())
                cleanup_account_deletion_files(
                    get_db(),
                    app.config["UPLOAD_FOLDER"],
                    audit_retention_days=app.config[
                        "ACCOUNT_DELETION_AUDIT_RETENTION_DAYS"
                    ],
                )
                last_source_cleanup_at = now
            _fail_exhausted_stale_jobs(get_db(), app.config)
            job = claim_video_job(
                get_db(), app.config, worker_id=worker_id
            )
            if job:
                process_claimed_video_job(job)
                continue
            stop.wait(poll_seconds)

        get_db().videoWorkerHeartbeats.update_one(
            {"_id": worker_id},
            {
                "$set": {
                    "status": "stopped",
                    "stoppedAt": datetime.now(UTC),
                    "updatedAt": datetime.now(UTC),
                }
            },
        )
        app.logger.info("Video worker stopped: %s", worker_id)


def prepare_video_worker_runtime(config) -> dict:
    provider = config.get(
        "TRANSCRIPTION_PROVIDER",
        "faster_whisper",
    )
    warmup_enabled = config.get(
        "VIDEO_WORKER_WARMUP_MODEL",
        False,
    )
    model_warmed = False
    if warmup_enabled and provider == "faster_whisper":
        warm_up_transcription_provider()
        model_warmed = True
    return {
        "transcriptionProvider": provider,
        "transcriptionModel": config.get(
            "FASTER_WHISPER_MODEL_SIZE"
        ),
        "modelWarmed": model_warmed,
    }


def cleanup_pending_video_sources(db, limit: int = 50) -> int:
    pending = db.videos.find(
        {
            "status": "completed",
            "deleteSourceAfterProcessing": True,
            "storedPath": {"$type": "string"},
            "sourceDeletionStatus": {"$ne": "deleted"},
        }
    ).limit(limit)
    deleted = 0
    for video in pending:
        if _delete_processed_video_source(db, video):
            deleted += 1
    return deleted


def _delete_processed_video_source(db, video: dict) -> bool:
    video_id = video["_id"]
    now = datetime.now(UTC)
    try:
        upload_root = Path(
            current_app.config["UPLOAD_FOLDER"]
        ).resolve()
        source_path = Path(video["storedPath"]).resolve()
        if source_path == upload_root or upload_root not in source_path.parents:
            raise ValueError("Stored video path is outside the upload folder")

        _remove_video_source_file(source_path)
        try:
            source_path.parent.rmdir()
        except OSError:
            pass
    except (OSError, TypeError, ValueError, KeyError) as error:
        current_app.logger.error(
            "Video source deletion failed for %s: %s",
            video_id,
            error,
        )
        db.videos.update_one(
            {"_id": video_id},
            {
                "$set": {
                    "sourceDeletionStatus": "failed",
                    "sourceDeletionError": str(error)[:1000],
                    "sourceDeletionLastAttemptAt": now,
                },
                "$inc": {"sourceDeletionAttempts": 1},
            },
        )
        return False

    db.videos.update_one(
        {"_id": video_id},
        {
            "$set": {
                "sourceDeletionStatus": "deleted",
                "sourceDeletedAt": now,
                "sourceDeletionLastAttemptAt": now,
            },
            "$inc": {"sourceDeletionAttempts": 1},
            "$unset": {
                "storedPath": "",
                "sourceDeletionError": "",
            },
        },
    )
    return True


def _remove_video_source_file(path: Path) -> None:
    path.unlink(missing_ok=True)


def _fail_claimed_job(
    db,
    job: dict,
    lock_query: dict,
    error: Exception,
    *,
    retryable: bool,
) -> None:
    now = datetime.now(UTC)
    error_message = str(error)[:2000] or error.__class__.__name__
    attempts = job.get("attempts", 1)
    max_attempts = job.get(
        "maxAttempts",
        current_app.config.get("VIDEO_JOB_MAX_ATTEMPTS", 3),
    )

    if retryable and attempts < max_attempts:
        base_delay = current_app.config.get(
            "VIDEO_JOB_RETRY_BASE_SECONDS", 15
        )
        max_delay = current_app.config.get(
            "VIDEO_JOB_RETRY_MAX_SECONDS", 900
        )
        delay = min(max_delay, base_delay * (2 ** max(0, attempts - 1)))
        retry_at = now + timedelta(seconds=delay)
        updated = db.videoProcessingJobs.update_one(
            lock_query,
            {
                "$set": {
                    "status": "queued",
                    "availableAt": retry_at,
                    "lastError": error_message,
                    "lastFailedAt": now,
                    "updatedAt": now,
                },
                "$unset": {
                    "lockedAt": "",
                    "lockedBy": "",
                    "lockToken": "",
                    "leaseExpiresAt": "",
                    "purgeAt": "",
                },
            },
        )
        if updated.modified_count == 1:
            db.videos.update_one(
                {"_id": job["videoId"]},
                {
                    "$set": {
                        "status": "processing",
                        "processingError": error_message,
                        "nextRetryAt": retry_at,
                        "updatedAt": now,
                    }
                },
            )
        return

    failed = db.videoProcessingJobs.update_one(
        lock_query,
        {
            "$set": {
                "status": "failed",
                "failedAt": now,
                "lastError": error_message,
                "purgeAt": _video_job_purge_at(
                    now,
                    current_app.config,
                ),
                "updatedAt": now,
            },
            "$unset": {
                "lockedAt": "",
                "lockedBy": "",
                "lockToken": "",
                "leaseExpiresAt": "",
            },
        },
    )
    if failed.modified_count == 1:
        _mark_video_and_user_failed(
            db, job["videoId"], job.get("userId"), error_message, now
        )


def _fail_exhausted_stale_jobs(db, config) -> int:
    now = datetime.now(UTC)
    max_attempts = config.get("VIDEO_JOB_MAX_ATTEMPTS", 3)
    stale_jobs = list(
        db.videoProcessingJobs.find(
            {
                "status": "processing",
                "leaseExpiresAt": {"$lte": now},
                "$expr": {
                    "$gte": [
                        {"$ifNull": ["$attempts", 0]},
                        {"$ifNull": ["$maxAttempts", max_attempts]},
                    ]
                },
            }
        ).limit(50)
    )
    failed_count = 0
    for job in stale_jobs:
        result = db.videoProcessingJobs.update_one(
            {
                "_id": job["_id"],
                "status": "processing",
                "leaseExpiresAt": {"$lte": now},
            },
            {
                "$set": {
                    "status": "failed",
                    "failedAt": now,
                    "lastError": "Worker lease expired after maximum attempts",
                    "purgeAt": _video_job_purge_at(
                        now,
                        config,
                    ),
                    "updatedAt": now,
                },
                "$unset": {
                    "lockedAt": "",
                    "lockedBy": "",
                    "lockToken": "",
                    "leaseExpiresAt": "",
                },
            },
        )
        if result.modified_count == 1:
            failed_count += 1
            _mark_video_and_user_failed(
                db,
                job["videoId"],
                job.get("userId"),
                "Worker lease expired after maximum attempts",
                now,
            )
    return failed_count


def _video_job_purge_at(terminal_at: datetime, config) -> datetime:
    return terminal_at + timedelta(
        seconds=config.get(
            "VIDEO_JOB_RETENTION_SECONDS",
            7 * 24 * 60 * 60,
        )
    )


def _mark_video_and_user_failed(
    db,
    video_id: ObjectId,
    user_id: ObjectId | None,
    error_message: str,
    failed_at: datetime,
) -> None:
    db.videos.update_one(
        {"_id": video_id},
        {
            "$set": {
                "status": "failed",
                "processingError": error_message,
                "updatedAt": failed_at,
            }
        },
    )
    if user_id is not None:
        db.users.update_one(
            {"_id": user_id, "latestVideoId": video_id},
            {
                "$set": {
                    "profileStatus": "video_processing_failed",
                    "videoStatus": "failed",
                    "updatedAt": failed_at,
                }
            },
        )


def _record_worker_heartbeat(
    db,
    worker_id: str,
    started_at: datetime,
    now: datetime,
    heartbeat_seconds: int,
    runtime_info: dict,
) -> None:
    db.videoWorkerHeartbeats.update_one(
        {"_id": worker_id},
        {
            "$set": {
                "status": "running",
                "host": socket.gethostname(),
                "processId": os.getpid(),
                **runtime_info,
                "lastSeenAt": now,
                "updatedAt": now,
                "expiresAt": now
                + timedelta(seconds=max(heartbeat_seconds * 3, 30)),
            },
            "$setOnInsert": {"startedAt": started_at},
        },
        upsert=True,
    )


def _worker_identity() -> str:
    configured = os.getenv("VIDEO_WORKER_ID")
    if configured:
        return configured
    return f"{socket.gethostname()}:{os.getpid()}"


class _JobLeaseHeartbeat:
    def __init__(
        self,
        db,
        lock_query: dict,
        lease_seconds: int,
        heartbeat_seconds: int,
    ):
        self.db = db
        self.lock_query = lock_query
        self.lease_seconds = lease_seconds
        self.heartbeat_seconds = min(
            max(1, heartbeat_seconds), max(1, lease_seconds // 2)
        )
        self.stop_event = Event()
        self.thread = Thread(
            target=self._run,
            name=f"video-job-heartbeat-{lock_query['_id']}",
            daemon=True,
        )

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, _error_type, _error, _traceback):
        self.stop_event.set()
        self.thread.join(timeout=2)

    def _run(self) -> None:
        while not self.stop_event.wait(self.heartbeat_seconds):
            now = datetime.now(UTC)
            result = self.db.videoProcessingJobs.update_one(
                self.lock_query,
                {
                    "$set": {
                        "leaseExpiresAt": now
                        + timedelta(seconds=self.lease_seconds),
                        "heartbeatAt": now,
                        "updatedAt": now,
                    }
                },
            )
            if result.modified_count != 1:
                return


def analyze_video(video: dict, transcript: dict) -> dict:
    path = Path(video["storedPath"])
    size_bytes = path.stat().st_size if path.exists() else 0
    filename_tokens = _tokenize(video.get("originalFilename", ""))
    transcript_text = transcript.get("text", "")
    inferred_skills = _infer_skills(filename_tokens, transcript_text)
    candidate_name = _extract_candidate_name(transcript_text)
    transcript_status = transcript.get("status", "unavailable")

    return {
        "engine": "local-video-processing-v2",
        "summary": _profile_summary(transcript_text, inferred_skills),
        "fileSizeBytes": size_bytes,
        "contentType": video.get("contentType"),
        "transcription": {
            "provider": transcript.get("provider"),
            "status": transcript_status,
            "language": transcript.get("metadata", {}).get("language"),
            "textLength": len(transcript_text),
        },
        "candidateName": candidate_name,
        "signals": {
            "filenameTokens": filename_tokens,
            "hasPlayableUpload": size_bytes > 0,
            "hasTranscript": bool(transcript_text),
        },
        "inferredSkills": inferred_skills,
        "warnings": transcript.get("warnings", []),
    }


def build_candidate_profile(user: dict, video: dict, analysis: dict, now: datetime) -> dict:
    skills = analysis["inferredSkills"] or ["iletişim", "takım çalışması", "öğrenmeye açıklık"]
    reviewed_name = (
        user.get("name")
        if user.get("nameStatus") in {
            "provided",
            "confirmed_by_worker",
            "corrected_by_worker",
        }
        else None
    )
    candidate_name = (
        reviewed_name
        or analysis.get("candidateName")
        or user.get("name")
        or "Video ile belirlenecek"
    )
    profile = {
        "userId": user["_id"],
        "latestVideoId": video["_id"],
        "name": candidate_name,
        "nameSource": (
            "worker_review"
            if reviewed_name
            else "video_inference"
        ),
        "summary": analysis["summary"],
        "skills": skills,
        "preferredRoles": _preferred_roles(skills),
        "availability": "belirtilmedi",
        "confidence": _profile_confidence(analysis),
        "source": analysis["engine"],
        "warnings": analysis["warnings"],
        "createdAt": now,
        "updatedAt": now,
    }
    if reviewed_name and user.get("profileReviewedAt"):
        profile["nameReviewedAt"] = user["profileReviewedAt"]
    return profile


def refresh_user_job_recommendations(
    db,
    user: dict,
    video: dict,
    profile: dict,
    now: datetime | None = None,
) -> list[dict]:
    if (
        db.users.count_documents(
            {
                "_id": user["_id"],
                "latestVideoId": video["_id"],
            },
            limit=1,
        )
        == 0
    ):
        return []
    timestamp = now or datetime.now(UTC)
    postings = list(
        db.jobPostings.find(
            {
                "employerKey": user.get("employerKey") or "default",
                "status": "published",
            }
        )
    )
    posting_catalog = postings
    if (
        not postings
        and current_app.config.get(
            "JOB_RECOMMENDATION_FALLBACK_ENABLED", False
        )
    ):
        posting_catalog = None
    recommendations = build_job_recommendations(
        user, video, profile, timestamp, posting_catalog
    )
    recommendation_ids = [item["_id"] for item in recommendations]
    db.jobRecommendations.delete_many(
        {
            "userId": user["_id"],
            "videoId": video["_id"],
            "_id": {"$nin": recommendation_ids},
        }
    )
    for recommendation in recommendations:
        existing = db.jobRecommendations.find_one(
            {"_id": recommendation["_id"]}
        )
        if existing and existing.get("createdAt"):
            recommendation["createdAt"] = existing["createdAt"]
        db.jobRecommendations.replace_one(
            {"_id": recommendation["_id"]},
            recommendation,
            upsert=True,
        )
    return recommendations


def build_job_recommendations(
    user: dict,
    video: dict,
    profile: dict,
    now: datetime,
    job_postings: list[dict] | None = None,
) -> list[dict]:
    skills = {skill.casefold() for skill in profile["skills"]}
    catalog = (
        [_posting_as_template(item) for item in job_postings]
        if job_postings is not None
        else JOB_TEMPLATES
    )
    recommendations = []
    for template in catalog:
        required_skills = template["requiredSkills"]
        overlap = len(
            skills.intersection(skill.casefold() for skill in required_skills)
        )
        if template.get("jobPostingId"):
            required_count = max(1, len(required_skills))
            optional_overlap = len(
                skills.intersection(
                    skill.casefold()
                    for skill in template.get("optionalSkills", [])
                )
            )
            score = min(
                98,
                45
                + round((overlap / required_count) * 45)
                + min(8, optional_overlap * 4),
            )
        else:
            score = min(98, template["baseScore"] + overlap * 6)
        recommendations.append(
            {
                "_id": _recommendation_id(video["_id"], template["key"]),
                "userId": user["_id"],
                "videoId": video["_id"],
                "employerKey": user.get("employerKey") or "default",
                "templateKey": template["key"],
                "jobPostingId": template.get("jobPostingId"),
                "title": template["title"],
                "company": template["company"],
                "location": template["location"],
                "requiredSkills": template["requiredSkills"],
                "matchScore": score,
                "reason": _recommendation_reason(profile, template, overlap),
                "createdAt": now,
                "updatedAt": now,
            }
        )

    limit = 5 if job_postings is not None else 3
    return sorted(
        recommendations,
        key=lambda item: item["matchScore"],
        reverse=True,
    )[:limit]


def _posting_as_template(posting: dict) -> dict:
    return {
        "key": f"posting-{posting['_id']}",
        "jobPostingId": posting["_id"],
        "title": posting["title"],
        "company": posting.get("company")
        or posting.get("employerKey")
        or "İşveren",
        "location": posting["location"],
        "requiredSkills": posting.get("requiredSkills", []),
        "optionalSkills": posting.get("optionalSkills", []),
        "baseScore": 45,
    }


def _tokenize(value: str) -> list[str]:
    normalized = value.lower().replace("_", " ").replace("-", " ").replace(".", " ")
    return [token for token in normalized.split() if token]


def _store_transcript(db, video: dict, transcript: dict) -> None:
    now = datetime.now(UTC)
    existing = db.videoTranscripts.find_one({"videoId": video["_id"]})
    transcript_doc = {
        **transcript,
        "videoId": video["_id"],
        "userId": video["userId"],
        "updatedAt": now,
    }
    transcript_doc.setdefault(
        "createdAt", (existing or {}).get("createdAt", now)
    )
    db.videoTranscripts.replace_one({"videoId": video["_id"]}, transcript_doc, upsert=True)


def _recommendation_id(video_id: ObjectId, template_key: str) -> ObjectId:
    digest = hashlib.sha256(
        f"{video_id}:{template_key}".encode("utf-8")
    ).hexdigest()
    return ObjectId(digest[:24])


def _infer_skills(tokens: list[str], transcript_text: str = "") -> list[str]:
    token_set = set(tokens)
    normalized_text = _normalize_text(transcript_text)
    skills = set()

    if token_set.intersection({"driver", "surucu", "sürücü", "lojistik", "logistics"}):
        skills.update(["lojistik", "araç kullanma"])
    if token_set.intersection({"technical", "teknik", "support", "destek"}):
        skills.update(["teknik destek", "problem çözme"])
    if token_set.intersection({"sales", "satis", "satış"}):
        skills.update(["müşteri iletişimi", "satış"])

    for skill, keywords in SKILL_KEYWORDS.items():
        if any(keyword in normalized_text for keyword in keywords):
            skills.add(skill)

    return sorted(skills)


def _preferred_roles(skills: list[str]) -> list[str]:
    if "kaynak" in skills:
        return ["Kaynak Ustası", "Bakım Onarım Teknisyeni"]
    if "tesisatçılık" in skills or "elektrik" in skills or "bakım onarım" in skills:
        return ["Bakım Onarım Teknisyeni", "Teknik Destek Elemanı"]
    if "lojistik" in skills:
        return ["Depo ve Lojistik Personeli", "Saha Operasyon Görevlisi"]
    if "teknik destek" in skills:
        return ["Teknik Destek Elemanı", "Saha Operasyon Görevlisi"]
    return ["Saha Operasyon Görevlisi", "Depo ve Lojistik Personeli"]


def _recommendation_reason(profile: dict, template: dict, overlap: int) -> str:
    if overlap:
        return f"{overlap} profil becerisi bu ilanla eşleşiyor."
    first_skill = profile["skills"][0] if profile["skills"] else "profil"
    return f"{first_skill} becerisi bu rol için başlangıç sinyali olarak değerlendirildi."


def _normalize_text(value: str) -> str:
    return value.casefold().replace("ı", "i")


def _extract_candidate_name(transcript_text: str) -> str | None:
    if not transcript_text:
        return None

    match = re.search(
        r"\b(?:adım|adim|ismim|benim adım|benim adim|ben)\s+"
        r"([A-Za-zÇĞİÖŞÜçğıöşü]+(?:\s+[A-Za-zÇĞİÖŞÜçğıöşü]+){1,3})",
        transcript_text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None

    candidate = re.split(r"[,.!?;:]", match.group(1), maxsplit=1)[0].strip()
    stop_words = {"kaynak", "işlerinde", "islerinde", "deneyimliyim", "çalışıyorum", "calisiyorum"}
    parts = [part for part in candidate.split() if part.casefold() not in stop_words]
    if len(parts) < 2:
        return None
    return " ".join(part[:1].upper() + part[1:] for part in parts[:3])


def _candidate_name_update(
    analysis: dict,
    user: dict,
) -> dict:
    if (
        user.get("name")
        and user.get("nameStatus")
        in {
            "provided",
            "confirmed_by_worker",
            "corrected_by_worker",
        }
    ):
        return {
            "name": user["name"],
            "nameStatus": user["nameStatus"],
            "profileReviewStatus": "confirmed",
        }
    candidate_name = analysis.get("candidateName")
    if not candidate_name:
        return {"profileReviewStatus": "pending"}
    return {
        "name": candidate_name,
        "nameStatus": "inferred_from_video",
        "profileReviewStatus": "pending",
    }


def _profile_summary(transcript_text: str, skills: list[str]) -> str:
    if transcript_text and skills:
        return f"Video CV transkribe edildi; aday {', '.join(skills[:4])} becerilerini vurguluyor."
    if transcript_text:
        return "Video CV transkribe edildi; aday profili konuşma içeriğine göre oluşturuldu."
    return "Video CV alındı, dosya doğrulandı ve aday profili mevcut sinyallerle oluşturuldu."


def _profile_confidence(analysis: dict) -> float:
    if analysis["signals"]["hasTranscript"] and analysis["inferredSkills"]:
        return 0.86
    if analysis["signals"]["hasTranscript"]:
        return 0.72
    if analysis["signals"]["hasPlayableUpload"]:
        return 0.48
    return 0.30
