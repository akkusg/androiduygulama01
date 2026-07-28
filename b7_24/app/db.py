from datetime import UTC, datetime, timedelta

from flask import Flask, current_app
from pymongo import ASCENDING, DESCENDING, MongoClient, UpdateOne
from pymongo.errors import DuplicateKeyError
from werkzeug.exceptions import BadRequest

from app.services.auth import VALID_STORED_PHONE, normalize_phone


def get_client() -> MongoClient:
    return current_app.extensions["mongo_client"]


def get_db():
    return get_client()[current_app.config["MONGO_DB_NAME"]]


def ensure_indexes() -> None:
    if current_app.extensions.get("mongo_indexes_ready"):
        return

    db = get_db()
    db.users.create_index([("phone", ASCENDING)], unique=True)
    phone_backfill = _backfill_legacy_user_phones(db)
    if phone_backfill["conflicts"] or phone_backfill["invalid"]:
        current_app.logger.warning(
            "User phone backfill left conflicts=%s invalid=%s",
            phone_backfill["conflicts"],
            phone_backfill["invalid"],
        )
    db.workerConsents.create_index(
        [
            ("userId", ASCENDING),
            ("type", ASCENDING),
            ("version", ASCENDING),
        ],
        unique=True,
    )
    db.workerConsents.create_index(
        [
            ("userId", ASCENDING),
            ("type", ASCENDING),
            ("revokedAt", ASCENDING),
        ]
    )
    db.workerInvitations.create_index(
        [("phone", ASCENDING), ("status", ASCENDING)],
        unique=True,
        partialFilterExpression={"status": "pending"},
    )
    db.workerInvitations.create_index(
        [("employerKey", ASCENDING), ("createdAt", DESCENDING)]
    )
    db.workerInvitations.create_index(
        [("purgeAt", ASCENDING)], expireAfterSeconds=0
    )
    db.otpChallenges.create_index([("phone", ASCENDING), ("createdAt", DESCENDING)])
    db.otpChallenges.create_index([("expiresAt", ASCENDING)], expireAfterSeconds=0)
    db.otpRateLimits.create_index(
        [("rateKey", ASCENDING), ("windowStart", ASCENDING)],
        unique=True,
    )
    db.otpRateLimits.create_index(
        [("expiresAt", ASCENDING)], expireAfterSeconds=0
    )
    db.actionRateLimits.create_index(
        [("rateKey", ASCENDING), ("windowStart", ASCENDING)],
        unique=True,
    )
    db.actionRateLimits.create_index(
        [("expiresAt", ASCENDING)], expireAfterSeconds=0
    )
    db.idempotencyRecords.create_index(
        [("scope", ASCENDING), ("idempotencyKey", ASCENDING)],
        unique=True,
    )
    db.idempotencyRecords.create_index(
        [("expiresAt", ASCENDING)], expireAfterSeconds=0
    )
    db.authSessions.create_index([("tokenHash", ASCENDING)], unique=True)
    db.authSessions.create_index([("expiresAt", ASCENDING)], expireAfterSeconds=0)
    db.accountDeletionRecords.create_index(
        [("status", ASCENDING), ("updatedAt", ASCENDING)]
    )
    db.accountDeletionRecords.create_index(
        [("purgeAt", ASCENDING)],
        expireAfterSeconds=0,
    )
    _backfill_completed_account_deletion_purge_times(
        db,
        current_app.config.get(
            "ACCOUNT_DELETION_AUDIT_RETENTION_DAYS",
            365,
        ),
    )
    db.adminLoginAttempts.create_index(
        [("attemptKey", ASCENDING), ("createdAt", DESCENDING)]
    )
    db.adminLoginAttempts.create_index(
        [("expiresAt", ASCENDING)], expireAfterSeconds=0
    )
    db.adminAuditEvents.create_index(
        [("employerKey", ASCENDING), ("createdAt", DESCENDING)]
    )
    db.adminAuditEvents.create_index(
        [
            ("employerKey", ASCENDING),
            ("outcome", ASCENDING),
            ("createdAt", DESCENDING),
        ]
    )
    db.adminAuditEvents.create_index(
        [("purgeAt", ASCENDING)], expireAfterSeconds=0
    )
    db.videos.create_index([("userId", ASCENDING), ("createdAt", ASCENDING)])
    db.videos.create_index(
        [
            ("deleteSourceAfterProcessing", ASCENDING),
            ("status", ASCENDING),
            ("sourceDeletionStatus", ASCENDING),
        ]
    )
    db.videoTranscripts.create_index([("videoId", ASCENDING)], unique=True)
    db.videoTranscripts.create_index([("userId", ASCENDING), ("createdAt", ASCENDING)])
    db.videoProcessingJobs.create_index([("videoId", ASCENDING)], unique=True)
    db.videoProcessingJobs.create_index([("userId", ASCENDING), ("createdAt", ASCENDING)])
    db.videoProcessingJobs.create_index(
        [("status", ASCENDING), ("availableAt", ASCENDING), ("createdAt", ASCENDING)]
    )
    db.videoProcessingJobs.create_index(
        [("purgeAt", ASCENDING)],
        expireAfterSeconds=0,
    )
    _backfill_terminal_video_job_purge_times(
        db,
        current_app.config.get(
            "VIDEO_JOB_RETENTION_SECONDS",
            7 * 24 * 60 * 60,
        ),
    )
    db.videoWorkerHeartbeats.create_index(
        [("expiresAt", ASCENDING)], expireAfterSeconds=0
    )
    db.candidateProfiles.create_index([("userId", ASCENDING)], unique=True)
    db.jobRecommendations.create_index([("userId", ASCENDING), ("matchScore", ASCENDING)])
    db.jobRecommendations.create_index([("userId", ASCENDING), ("videoId", ASCENDING)])
    db.jobRecommendations.create_index(
        [("jobPostingId", ASCENDING), ("userId", ASCENDING)]
    )
    db.jobPostings.create_index(
        [("employerKey", ASCENDING), ("status", ASCENDING), ("createdAt", DESCENDING)]
    )
    db.jobApplications.create_index([("userId", ASCENDING), ("jobRecommendationId", ASCENDING)], unique=True)
    db.jobApplications.create_index(
        [("userId", ASCENDING), ("jobPostingId", ASCENDING)],
        unique=True,
        partialFilterExpression={"jobPostingId": {"$type": "objectId"}},
    )
    db.jobApplications.create_index(
        [("employerKey", ASCENDING), ("createdAt", DESCENDING)]
    )
    db.jobApplications.create_index(
        [
            ("employerKey", ASCENDING),
            ("status", ASCENDING),
            ("createdAt", DESCENDING),
        ]
    )
    db.jobHiringSlots.create_index(
        [("jobPostingId", ASCENDING), ("slot", ASCENDING)],
        unique=True,
    )
    db.jobHiringSlots.create_index(
        [("applicationId", ASCENDING)], unique=True
    )
    db.workerSupportConfigs.create_index([("employerKey", ASCENDING)], unique=True)
    db.workerSupportAssignments.create_index(
        [("userId", ASCENDING), ("employerKey", ASCENDING)],
        unique=True,
    )
    db.workerSupportAssignments.create_index(
        [("employerKey", ASCENDING), ("updatedAt", DESCENDING)]
    )
    db.workerPushRegistrations.create_index(
        [("userId", ASCENDING), ("installationId", ASCENDING)],
        unique=True,
    )
    db.workerPushRegistrations.create_index(
        [("fidHash", ASCENDING)],
        unique=True,
        partialFilterExpression={"fidHash": {"$type": "string"}},
    )
    db.workerPushRegistrations.create_index(
        [("active", ASCENDING), ("lastSeenAt", ASCENDING)]
    )
    db.workerPushRegistrations.create_index(
        [("purgeAt", ASCENDING)],
        expireAfterSeconds=0,
    )
    db.pushNotificationJobs.create_index(
        [
            ("eventKey", ASCENDING),
            ("deviceRegistrationId", ASCENDING),
        ],
        unique=True,
    )
    db.pushNotificationJobs.create_index(
        [
            ("status", ASCENDING),
            ("availableAt", ASCENDING),
            ("createdAt", ASCENDING),
        ]
    )
    db.pushNotificationJobs.create_index(
        [("purgeAt", ASCENDING)],
        expireAfterSeconds=0,
    )
    db.pushWorkerHeartbeats.create_index(
        [("expiresAt", ASCENDING)],
        expireAfterSeconds=0,
    )
    db.workerQuestions.update_many(
        {
            "status": {"$exists": False},
            "matchedKeywords.0": {"$exists": True},
        },
        {"$set": {"status": "auto_answered"}},
    )
    db.workerQuestions.update_many(
        {"status": {"$exists": False}},
        {"$set": {"status": "answered"}},
    )
    db.workerQuestions.create_index([("userId", ASCENDING), ("createdAt", ASCENDING)])
    db.workerQuestions.create_index(
        [
            ("userId", ASCENDING),
            ("status", ASCENDING),
            ("createdAt", DESCENDING),
        ]
    )
    db.workerQuestions.create_index(
        [
            ("employerKey", ASCENDING),
            ("status", ASCENDING),
            ("createdAt", DESCENDING),
        ]
    )
    db.workerAssessmentResults.create_index([("userId", ASCENDING), ("assessmentId", ASCENDING)], unique=True)
    db.workerTrainingProgress.create_index([("userId", ASCENDING), ("trainingId", ASCENDING)], unique=True)
    db.workerShuttleRequests.create_index([("userId", ASCENDING), ("status", ASCENDING)])
    db.workerShuttleRequests.create_index(
        [("employerKey", ASCENDING), ("createdAt", DESCENDING)]
    )
    db.workerShuttleRequests.create_index(
        [
            ("employerKey", ASCENDING),
            ("status", ASCENDING),
            ("createdAt", DESCENDING),
        ]
    )
    current_app.extensions["mongo_indexes_ready"] = True


def _backfill_legacy_user_phones(db) -> dict[str, int]:
    result = {"migrated": 0, "conflicts": 0, "invalid": 0}
    users = db.users.find(
        {"phone": {"$not": VALID_STORED_PHONE}},
        {"phone": 1},
    )
    for user in users:
        raw_phone = user.get("phone")
        try:
            normalized_phone = normalize_phone(raw_phone)
        except BadRequest:
            result["invalid"] += 1
            continue
        if db.users.find_one(
            {
                "_id": {"$ne": user["_id"]},
                "phone": normalized_phone,
            },
            {"_id": 1},
        ):
            result["conflicts"] += 1
            continue
        try:
            update = db.users.update_one(
                {
                    "_id": user["_id"],
                    "phone": raw_phone,
                },
                {
                    "$set": {
                        "phone": normalized_phone,
                        "updatedAt": datetime.now(UTC),
                    }
                },
            )
        except DuplicateKeyError:
            result["conflicts"] += 1
            continue
        result["migrated"] += update.modified_count
    return result


def _backfill_terminal_video_job_purge_times(
    db,
    retention_seconds: int,
) -> int:
    operations = []
    modified = 0
    jobs = db.videoProcessingJobs.find(
        {
            "status": {"$in": ["completed", "failed"]},
            "purgeAt": {"$exists": False},
        },
        {
            "completedAt": 1,
            "failedAt": 1,
            "updatedAt": 1,
            "createdAt": 1,
        },
    )
    for job in jobs:
        terminal_at = (
            job.get("completedAt")
            or job.get("failedAt")
            or job.get("updatedAt")
            or job.get("createdAt")
            or datetime.now(UTC)
        )
        operations.append(
            UpdateOne(
                {
                    "_id": job["_id"],
                    "purgeAt": {"$exists": False},
                },
                {
                    "$set": {
                        "purgeAt": terminal_at
                        + timedelta(seconds=retention_seconds)
                    }
                },
            )
        )
        if len(operations) >= 500:
            modified += db.videoProcessingJobs.bulk_write(
                operations,
                ordered=False,
            ).modified_count
            operations = []
    if operations:
        modified += db.videoProcessingJobs.bulk_write(
            operations,
            ordered=False,
        ).modified_count
    return modified


def _backfill_completed_account_deletion_purge_times(
    db,
    retention_days: int,
) -> int:
    operations = []
    modified = 0
    records = db.accountDeletionRecords.find(
        {
            "status": "completed",
            "purgeAt": {"$exists": False},
        },
        {
            "completedAt": 1,
            "updatedAt": 1,
            "requestedAt": 1,
        },
    )
    for record in records:
        completed_at = (
            record.get("completedAt")
            or record.get("updatedAt")
            or record.get("requestedAt")
            or datetime.now(UTC)
        )
        operations.append(
            UpdateOne(
                {
                    "_id": record["_id"],
                    "status": "completed",
                    "purgeAt": {"$exists": False},
                },
                {
                    "$set": {
                        "purgeAt": completed_at
                        + timedelta(days=retention_days)
                    }
                },
            )
        )
        if len(operations) >= 500:
            modified += db.accountDeletionRecords.bulk_write(
                operations,
                ordered=False,
            ).modified_count
            operations = []
    if operations:
        modified += db.accountDeletionRecords.bulk_write(
            operations,
            ordered=False,
        ).modified_count
    return modified


def init_db(app: Flask) -> None:
    app.extensions["mongo_client"] = MongoClient(
        app.config["MONGO_URI"],
        serverSelectionTimeoutMS=2000,
        tz_aware=True,
    )
    app.extensions["mongo_indexes_ready"] = False
