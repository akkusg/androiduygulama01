from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from bson import ObjectId
from werkzeug.exceptions import NotFound


PERSONAL_COLLECTIONS = (
    "workerConsents",
    "videoTranscripts",
    "videoProcessingJobs",
    "videos",
    "candidateProfiles",
    "jobRecommendations",
    "workerQuestions",
    "workerSupportAssignments",
    "workerPushRegistrations",
    "pushNotificationJobs",
    "workerAssessmentResults",
    "workerTrainingProgress",
    "workerShuttleRequests",
)
ACTION_RATE_LIMIT_SCOPES = (
    "video-upload",
    "worker-question",
)


def delete_worker_account(
    db,
    user_id: ObjectId,
    upload_folder: str,
    audit_retention_days: int = 365,
) -> dict:
    now = datetime.now(UTC)
    deletion = db.accountDeletionRecords.find_one({"_id": user_id})
    user = db.users.find_one({"_id": user_id})
    if user is None and deletion is None:
        raise NotFound("User not found")
    if deletion and deletion.get("status") == "completed":
        return deletion

    phone = (user or {}).get("phone") or (deletion or {}).get("phone")
    db.accountDeletionRecords.update_one(
        {"_id": user_id},
        {
            "$set": {
                "status": "processing",
                "phone": phone,
                "updatedAt": now,
            },
            "$setOnInsert": {"requestedAt": now},
        },
        upsert=True,
    )

    videos = list(db.videos.find({"userId": user_id}))
    source_paths = [
        video["storedPath"]
        for video in videos
        if isinstance(video.get("storedPath"), str)
    ]

    db.users.delete_one({"_id": user_id})
    _anonymize_job_applications(db, user_id, now)
    for collection_name in PERSONAL_COLLECTIONS:
        db[collection_name].delete_many({"userId": user_id})

    if phone:
        db.workerInvitations.delete_many({"phone": phone})
        db.otpChallenges.delete_many({"phone": phone})
        db.otpRateLimits.delete_many(
            {"rateKey": _rate_key("otp-phone", phone)}
        )

    for scope in ACTION_RATE_LIMIT_SCOPES:
        db.actionRateLimits.delete_many(
            {"rateKey": _rate_key(scope, str(user_id))}
        )
    db.idempotencyRecords.delete_many(
        {"scope": {"$regex": f"^{re.escape(str(user_id))}:"}}
    )

    pending_paths, cleanup_errors = _delete_source_paths(
        upload_folder,
        source_paths,
    )
    status = (
        "pending_file_cleanup"
        if pending_paths
        else "failed"
        if cleanup_errors
        else "completed"
    )
    updated_at = datetime.now(UTC)
    update = {
        "$set": {
            "status": status,
            "pendingSourcePaths": pending_paths,
            "fileCleanupErrors": cleanup_errors,
            "updatedAt": updated_at,
        },
        "$unset": {"phone": ""},
    }
    if status == "completed":
        update["$set"].update(
            {
                "completedAt": updated_at,
                "purgeAt": updated_at
                + timedelta(days=audit_retention_days),
            }
        )
    db.accountDeletionRecords.update_one({"_id": user_id}, update)
    db.authSessions.delete_many({"userId": user_id})
    return db.accountDeletionRecords.find_one({"_id": user_id})


def cleanup_account_deletion_files(
    db,
    upload_folder: str,
    limit: int = 50,
    audit_retention_days: int = 365,
) -> int:
    records = list(
        db.accountDeletionRecords.find(
            {
                "status": "pending_file_cleanup",
                "pendingSourcePaths.0": {"$exists": True},
            }
        ).limit(limit)
    )
    completed = 0
    for record in records:
        pending_paths, cleanup_errors = _delete_source_paths(
            upload_folder,
            record.get("pendingSourcePaths", []),
        )
        now = datetime.now(UTC)
        status = (
            "pending_file_cleanup"
            if pending_paths
            else "failed"
            if cleanup_errors
            else "completed"
        )
        update = {
            "$set": {
                "status": status,
                "pendingSourcePaths": pending_paths,
                "fileCleanupErrors": cleanup_errors,
                "updatedAt": now,
            }
        }
        if status == "completed":
            update["$set"].update(
                {
                    "completedAt": now,
                    "purgeAt": now
                    + timedelta(days=audit_retention_days),
                }
            )
            completed += 1
        db.accountDeletionRecords.update_one(
            {"_id": record["_id"]},
            update,
        )
    return completed


def account_deletion_requested(db, user_id: ObjectId) -> bool:
    return (
        db.accountDeletionRecords.find_one(
            {"_id": user_id},
            projection={"_id": 1},
        )
        is not None
    )


def purge_worker_processing_derivatives(db, user_id: ObjectId) -> None:
    db.videoTranscripts.delete_many({"userId": user_id})
    db.candidateProfiles.delete_many({"userId": user_id})
    db.jobRecommendations.delete_many({"userId": user_id})


def _anonymize_job_applications(
    db,
    user_id: ObjectId,
    deleted_at: datetime,
) -> None:
    applications = db.jobApplications.find({"userId": user_id})
    for application in applications:
        sanitized_history = [
            {
                "status": item.get("status"),
                "changedAt": item.get("changedAt"),
            }
            for item in application.get("statusHistory", [])
            if item.get("status")
        ]
        db.jobApplications.update_one(
            {"_id": application["_id"]},
            {
                "$set": {
                    "candidate": {
                        "name": "Silinen kullanıcı",
                        "phone": None,
                        "profileStatus": "deleted",
                        "skills": [],
                        "summary": None,
                    },
                    "coverNote": "",
                    "statusHistory": sanitized_history,
                    "accountDeletedAt": deleted_at,
                    "updatedAt": deleted_at,
                }
            },
        )


def _delete_source_paths(
    upload_folder: str,
    source_paths: list[str],
) -> tuple[list[str], list[str]]:
    upload_root = Path(upload_folder).resolve()
    pending_paths = []
    cleanup_errors = []
    for raw_path in source_paths:
        try:
            source_path = Path(raw_path).resolve()
            if (
                source_path == upload_root
                or upload_root not in source_path.parents
            ):
                raise ValueError(
                    "Stored video path is outside the upload folder"
                )
            source_path.unlink(missing_ok=True)
            try:
                source_path.parent.rmdir()
            except OSError:
                pass
        except (OSError, TypeError) as error:
            pending_paths.append(raw_path)
            cleanup_errors.append(str(error)[:1000])
        except ValueError as error:
            cleanup_errors.append(str(error))
    return pending_paths, cleanup_errors


def _rate_key(scope: str, subject: str) -> str:
    return hashlib.sha256(
        f"{scope}:{subject}".encode("utf-8")
    ).hexdigest()
