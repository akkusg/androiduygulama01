from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from pymongo.errors import DuplicateKeyError
from werkzeug.exceptions import Conflict

from app.services.auth import VALID_STORED_PHONE, normalize_phone


def stored_phone_is_valid(value) -> bool:
    return (
        isinstance(value, str)
        and VALID_STORED_PHONE.fullmatch(value) is not None
    )


def build_worker_data_hygiene_record(db, worker: dict) -> dict:
    worker_id = worker["_id"]
    auth_session_count = db.authSessions.count_documents(
        {"userId": worker_id}
    )
    video_count = db.videos.count_documents({"userId": worker_id})
    application_count = db.jobApplications.count_documents(
        {"userId": worker_id}
    )
    support_record_count = sum(
        db[collection_name].count_documents({"userId": worker_id})
        for collection_name in (
            "workerAssessmentResults",
            "workerTrainingProgress",
            "workerShuttleRequests",
            "workerQuestions",
        )
    )
    common_blockers = []
    if stored_phone_is_valid(worker.get("phone")):
        common_blockers.append("phone_valid")
    if worker.get("phoneVerifiedAt") is not None:
        common_blockers.append("phone_verified")
    if auth_session_count:
        common_blockers.append("auth_sessions")

    return {
        "phoneValid": stored_phone_is_valid(worker.get("phone")),
        "canCorrectPhone": not common_blockers,
        "correctionBlockers": common_blockers,
        "canCleanup": not common_blockers and video_count == 0,
        "cleanupBlockers": [
            *common_blockers,
            *(["videos"] if video_count else []),
        ],
        "authSessionCount": auth_session_count,
        "videoCount": video_count,
        "applicationCount": application_count,
        "supportRecordCount": support_record_count,
    }


def build_data_hygiene_report(
    db,
    employer_key: str | None = None,
    limit: int = 1000,
) -> dict:
    query: dict = {"phone": {"$not": VALID_STORED_PHONE}}
    if employer_key:
        query["employerKey"] = employer_key
    total = db.users.count_documents(query)
    workers = list(
        db.users.find(query)
        .sort("createdAt", 1)
        .limit(limit)
    )
    by_employer = {
        item["_id"] or "default": item["count"]
        for item in db.users.aggregate(
            [
                {"$match": query},
                {
                    "$group": {
                        "_id": "$employerKey",
                        "count": {"$sum": 1},
                    }
                },
                {"$sort": {"_id": 1}},
            ]
        )
    }
    return {
        "status": "ok" if total == 0 else "attention_required",
        "invalidPhoneWorkers": total,
        "byEmployer": by_employer,
        "truncated": total > len(workers),
        "workers": [
            {
                "id": str(worker["_id"]),
                "employerKey": worker.get("employerKey", "default"),
                "maskedPhone": _mask_phone(worker.get("phone")),
                **build_worker_data_hygiene_record(db, worker),
            }
            for worker in workers
        ],
    }


def correct_invalid_worker_phone(
    db,
    worker: dict,
    raw_phone,
) -> dict:
    state = build_worker_data_hygiene_record(db, worker)
    if not state["canCorrectPhone"]:
        raise Conflict(
            "Only unverified legacy workers without sessions can be corrected"
        )

    phone = normalize_phone(raw_phone)
    existing = db.users.find_one(
        {
            "phone": phone,
            "_id": {"$ne": worker["_id"]},
        },
        projection={"_id": 1},
    )
    if existing is not None:
        raise Conflict("A worker with this phone already exists")

    now = datetime.now(UTC)
    old_phone = worker.get("phone")
    try:
        result = db.users.update_one(
            {
                "_id": worker["_id"],
                "phone": old_phone,
                "phoneVerifiedAt": None,
            },
            {
                "$set": {
                    "phone": phone,
                    "updatedAt": now,
                }
            },
        )
    except DuplicateKeyError as error:
        raise Conflict(
            "A worker with this phone already exists"
        ) from error
    if result.modified_count != 1:
        raise Conflict("Worker changed while the phone was being corrected")

    db.jobApplications.update_many(
        {
            "userId": worker["_id"],
            "accountDeletedAt": {"$exists": False},
        },
        {
            "$set": {
                "candidate.phone": phone,
                "updatedAt": now,
            }
        },
    )
    if isinstance(old_phone, str) and old_phone:
        db.workerInvitations.delete_many({"phone": old_phone})
        db.otpChallenges.delete_many({"phone": old_phone})
        db.otpRateLimits.delete_many(
            {"rateKey": _rate_key("otp-phone", old_phone)}
        )
    return db.users.find_one({"_id": worker["_id"]})


def legacy_worker_cleanup_allowed(db, worker: dict) -> bool:
    return build_worker_data_hygiene_record(db, worker)["canCleanup"]


def _rate_key(scope: str, subject: str) -> str:
    return hashlib.sha256(
        f"{scope}:{subject}".encode("utf-8")
    ).hexdigest()


def _mask_phone(value) -> str:
    if not isinstance(value, str) or len(value) < 5:
        return "invalid"
    return f"{value[:3]}{'*' * (len(value) - 5)}{value[-2:]}"
