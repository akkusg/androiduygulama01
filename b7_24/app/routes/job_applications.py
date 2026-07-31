from datetime import UTC, datetime
from uuid import uuid4

from bson import ObjectId
from flask import Blueprint, jsonify, request
from pymongo.errors import DuplicateKeyError
from werkzeug.exceptions import BadRequest, Conflict, NotFound

from app.auth import require_employer, require_worker
from app.db import get_db
from app.services.idempotency import idempotent_worker_action
from app.services.push_notifications import (
    enqueue_application_status_push,
)
from app.serializers import serialize_job_application
from app.validation import parse_pagination, require_json_fields


job_applications_bp = Blueprint("job_applications", __name__)

APPLICATION_STATUSES = {
    "submitted",
    "reviewing",
    "shortlisted",
    "offered",
    "offer_declined",
    "rejected",
    "hired",
    "withdrawn",
}
WORKER_WITHDRAWABLE_STATUSES = {
    "submitted",
    "reviewing",
    "shortlisted",
}
APPLICATION_STATUS_TRANSITIONS = {
    "submitted": {
        "reviewing", "shortlisted", "offered", "rejected", "hired"
    },
    "reviewing": {"shortlisted", "offered", "rejected", "hired"},
    "shortlisted": {"reviewing", "offered", "rejected", "hired"},
    "offered": {"reviewing", "rejected", "hired"},
    "offer_declined": {"reviewing", "offered", "rejected"},
    "rejected": {"reviewing"},
    "hired": set(),
    "withdrawn": set(),
}
INTERVIEW_APPLICATION_STATUSES = {"reviewing", "shortlisted"}
INTERVIEW_TYPES = {"onsite", "phone", "video"}
INTERVIEW_RESPONSE_STATUSES = {"confirmed", "declined"}
OFFER_RESPONSE_STATUSES = {"accepted", "declined"}


@job_applications_bp.post("/api/users/<user_id>/job-applications")
@require_worker
@idempotent_worker_action
def create_job_application(user_id: str):
    user = _get_user(user_id)
    payload = request.get_json(silent=True) or {}
    require_json_fields(payload, ["jobRecommendationId"])

    job_recommendation_id = payload["jobRecommendationId"]
    if not ObjectId.is_valid(job_recommendation_id):
        raise BadRequest("Invalid job recommendation id")

    db = get_db()
    recommendation = db.jobRecommendations.find_one(
        {"_id": ObjectId(job_recommendation_id), "userId": user["_id"]}
    )
    if recommendation is None:
        raise NotFound("Job recommendation not found")

    posting_id = recommendation.get("jobPostingId")
    if posting_id is not None:
        posting = db.jobPostings.find_one(
            {
                "_id": posting_id,
                "employerKey": recommendation.get("employerKey"),
                "status": "published",
            }
        )
        if posting is None:
            raise Conflict("This job posting is no longer accepting applications")

    existing_query = {
        "userId": user["_id"],
        (
            "jobPostingId"
            if posting_id is not None
            else "jobRecommendationId"
        ): posting_id or recommendation["_id"],
    }
    existing = db.jobApplications.find_one(existing_query)
    if existing is not None:
        return jsonify({"jobApplication": serialize_job_application(existing)}), 200

    cover_note = _optional_text(payload, "coverNote", 1000)
    now = datetime.now(UTC)
    profile = db.candidateProfiles.find_one({"userId": user["_id"]})
    application = {
        "userId": user["_id"],
        "jobRecommendationId": recommendation["_id"],
        "jobPostingId": posting_id,
        "employerKey": recommendation.get("employerKey")
        or user.get("employerKey")
        or "default",
        "status": "submitted",
        "coverNote": cover_note,
        "job": _job_snapshot(recommendation),
        "candidate": _candidate_snapshot(user, profile),
        "statusHistory": [
            {"status": "submitted", "note": "Başvuru alındı.", "changedAt": now}
        ],
        "createdAt": now,
        "updatedAt": now,
    }
    try:
        result = db.jobApplications.insert_one(application)
        application["_id"] = result.inserted_id
    except DuplicateKeyError:
        existing = db.jobApplications.find_one(existing_query)
        if existing is None:
            raise
        return (
            jsonify(
                {"jobApplication": serialize_job_application(existing)}
            ),
            200,
        )
    return jsonify({"jobApplication": serialize_job_application(application)}), 201


@job_applications_bp.get("/api/users/<user_id>/job-applications")
@require_worker
def list_user_job_applications(user_id: str):
    user = _get_user(user_id)
    page, limit = parse_pagination(request.args)
    query = {"userId": user["_id"]}
    db = get_db()
    total = db.jobApplications.count_documents(query)
    applications = list(
        db.jobApplications.find(query)
        .sort("createdAt", -1)
        .skip((page - 1) * limit)
        .limit(limit)
    )
    return jsonify(
        {
            "jobApplications": [
                serialize_job_application(item)
                for item in applications
            ],
            "pagination": _pagination(page, limit, total),
        }
    )


@job_applications_bp.post(
    "/api/users/<user_id>/job-applications/"
    "<application_id>/withdraw"
)
@require_worker
@idempotent_worker_action
def withdraw_user_job_application(
    user_id: str,
    application_id: str,
):
    user = _get_user(user_id)
    if not ObjectId.is_valid(application_id):
        raise BadRequest("Invalid job application id")

    db = get_db()
    application = db.jobApplications.find_one(
        {
            "_id": ObjectId(application_id),
            "userId": user["_id"],
        }
    )
    if application is None:
        raise NotFound("Job application not found")
    if application.get("status") == "withdrawn":
        return jsonify(
            {
                "jobApplication": serialize_job_application(
                    application
                )
            }
        )
    if (
        application.get("status")
        not in WORKER_WITHDRAWABLE_STATUSES
    ):
        raise Conflict(
            "Job application can no longer be withdrawn"
        )

    now = datetime.now(UTC)
    result = db.jobApplications.update_one(
        {
            "_id": application["_id"],
            "userId": user["_id"],
            "status": application["status"],
        },
        {
            "$set": {
                "status": "withdrawn",
                "withdrawnAt": now,
                "updatedAt": now,
            },
            "$push": {
                "statusHistory": {
                    "status": "withdrawn",
                    "note": "Çalışan başvurusunu geri çekti.",
                    "changedAt": now,
                }
            },
        },
    )
    if result.modified_count != 1:
        raise Conflict("Job application changed concurrently")
    updated = db.jobApplications.find_one(
        {"_id": application["_id"]}
    )
    return jsonify(
        {"jobApplication": serialize_job_application(updated)}
    )


@job_applications_bp.post(
    "/api/users/<user_id>/job-applications/"
    "<application_id>/interview-response"
)
@require_worker
@idempotent_worker_action
def respond_to_job_interview(
    user_id: str,
    application_id: str,
):
    user = _get_user(user_id)
    if not ObjectId.is_valid(application_id):
        raise BadRequest("Invalid job application id")

    payload = request.get_json(silent=True) or {}
    require_json_fields(payload, ["status"])
    response_status = payload["status"]
    if (
        not isinstance(response_status, str)
        or response_status not in INTERVIEW_RESPONSE_STATUSES
    ):
        raise BadRequest("Invalid interview response status")
    note = _optional_text(payload, "note", 500)
    if response_status == "declined" and not note:
        raise BadRequest(
            "note is required when declining an interview"
        )

    db = get_db()
    application = db.jobApplications.find_one(
        {
            "_id": ObjectId(application_id),
            "userId": user["_id"],
        }
    )
    if application is None:
        raise NotFound("Job application not found")
    if application.get("status") not in INTERVIEW_APPLICATION_STATUSES:
        raise Conflict("Job application has no active interview")

    interview = application.get("interview")
    if not interview:
        raise Conflict("Job application has no scheduled interview")
    now = datetime.now(UTC)
    scheduled_at = interview.get("scheduledAt")
    if not isinstance(scheduled_at, datetime) or scheduled_at <= now:
        raise Conflict("Scheduled interview is no longer active")

    current_response = interview.get("response") or {}
    if (
        current_response.get("status") == response_status
        and current_response.get("note", "") == note
    ):
        return jsonify(
            {"jobApplication": serialize_job_application(application)}
        )

    response = {
        "status": response_status,
        "note": note,
        "respondedAt": now,
    }
    update_query = {
        "_id": application["_id"],
        "userId": user["_id"],
        "status": application["status"],
        "interview.scheduledAt": scheduled_at,
    }
    if interview.get("updatedAt") is not None:
        update_query["interview.updatedAt"] = interview["updatedAt"]
    result = db.jobApplications.update_one(
        update_query,
        {
            "$set": {
                "interview.response": response,
                "updatedAt": now,
            }
        },
    )
    if result.modified_count != 1:
        raise Conflict("Interview plan changed concurrently")
    updated = db.jobApplications.find_one(
        {"_id": application["_id"]}
    )
    return jsonify(
        {"jobApplication": serialize_job_application(updated)}
    )


@job_applications_bp.post(
    "/api/users/<user_id>/job-applications/"
    "<application_id>/offer-response"
)
@require_worker
@idempotent_worker_action
def respond_to_job_offer(
    user_id: str,
    application_id: str,
):
    user = _get_user(user_id)
    if not ObjectId.is_valid(application_id):
        raise BadRequest("Invalid job application id")

    payload = request.get_json(silent=True) or {}
    require_json_fields(payload, ["status"])
    response_status = payload["status"]
    if (
        not isinstance(response_status, str)
        or response_status not in OFFER_RESPONSE_STATUSES
    ):
        raise BadRequest("Invalid job offer response status")
    note = _optional_text(payload, "note", 500)
    if response_status == "declined" and not note:
        raise BadRequest("note is required when declining a job offer")

    db = get_db()
    application = db.jobApplications.find_one(
        {
            "_id": ObjectId(application_id),
            "userId": user["_id"],
        }
    )
    if application is None:
        raise NotFound("Job application not found")

    offer = application.get("offer") or {}
    current_response = offer.get("response") or {}
    resulting_status = (
        "hired" if response_status == "accepted" else "offer_declined"
    )
    if (
        application.get("status") == resulting_status
        and current_response.get("status") == response_status
        and current_response.get("note", "") == note
    ):
        return jsonify(
            {"jobApplication": serialize_job_application(application)}
        )
    if application.get("status") != "offered" or not offer:
        raise Conflict("Job application has no active offer")

    now = datetime.now(UTC)
    expires_at = offer.get("expiresAt")
    if not isinstance(expires_at, datetime) or expires_at <= now:
        raise Conflict("Job offer has expired")

    reservation = None
    reservation_created = False
    if response_status == "accepted" and application.get("jobPostingId"):
        posting = db.jobPostings.find_one(
            {
                "_id": application["jobPostingId"],
                "employerKey": application.get("employerKey"),
            }
        )
        if posting is not None:
            reservation, reservation_created = _reserve_hiring_slot(
                db,
                posting,
                application,
                now,
            )

    response = {
        "status": response_status,
        "note": note,
        "respondedAt": now,
    }
    update_operation = {
        "$set": {
            "status": resulting_status,
            "offer.response": response,
            "updatedAt": now,
        },
        "$push": {
            "statusHistory": {
                "status": resulting_status,
                "note": (
                    "Çalışan iş teklifini kabul etti."
                    if response_status == "accepted"
                    else "Çalışan iş teklifini reddetti."
                ),
                "changedAt": now,
            }
        },
    }
    if reservation is not None:
        update_operation["$set"]["hiringSlot"] = reservation["slot"]
    if response_status == "declined":
        update_operation["$unset"] = {"hiringSlot": ""}

    try:
        result = db.jobApplications.update_one(
            {
                "_id": application["_id"],
                "userId": user["_id"],
                "status": "offered",
                "offer.expiresAt": expires_at,
                "offer.updatedAt": offer.get("updatedAt"),
            },
            update_operation,
        )
    except Exception:
        if reservation_created:
            _release_application_hiring_slot(db, application["_id"])
        raise
    if result.modified_count != 1:
        if reservation_created:
            _release_application_hiring_slot(db, application["_id"])
        raise Conflict("Job offer changed concurrently")
    if response_status == "declined":
        _release_application_hiring_slot(db, application["_id"])

    updated = db.jobApplications.find_one(
        {"_id": application["_id"]}
    )
    return jsonify(
        {"jobApplication": serialize_job_application(updated)}
    )


@job_applications_bp.get("/api/employers/<employer_key>/job-applications")
@require_employer
def list_employer_job_applications(employer_key: str):
    status = request.args.get("status")
    if status and status not in APPLICATION_STATUSES:
        raise BadRequest("Invalid application status")

    query = {"employerKey": employer_key}
    if status:
        query["status"] = status

    page, limit = parse_pagination(request.args)
    db = get_db()
    total = db.jobApplications.count_documents(query)
    applications = list(
        db.jobApplications.find(query)
        .sort("createdAt", -1)
        .skip((page - 1) * limit)
        .limit(limit)
    )
    return jsonify(
        {
            "jobApplications": [
                serialize_job_application(item)
                for item in applications
            ],
            "pagination": _pagination(page, limit, total),
        }
    )


@job_applications_bp.patch("/api/employers/<employer_key>/job-applications/<application_id>")
@require_employer
def update_employer_job_application(employer_key: str, application_id: str):
    if not ObjectId.is_valid(application_id):
        raise BadRequest("Invalid job application id")

    payload = request.get_json(silent=True) or {}
    require_json_fields(payload, ["status"])
    status = payload["status"]
    if (
        not isinstance(status, str)
        or status not in APPLICATION_STATUSES
    ):
        raise BadRequest("Invalid application status")

    db = get_db()
    application = db.jobApplications.find_one(
        {"_id": ObjectId(application_id), "employerKey": employer_key}
    )
    if application is None:
        raise NotFound("Job application not found")
    now = datetime.now(UTC)
    interview_provided = "interview" in payload
    interview = _parse_interview(payload, now)
    offer_provided = "offer" in payload
    offer = _parse_offer(payload, now)
    if (
        interview_provided
        and interview is not None
        and status not in INTERVIEW_APPLICATION_STATUSES
    ):
        raise BadRequest(
            "Interview can only be scheduled for an active application"
        )
    if offer_provided and (status != "offered" or offer is None):
        raise BadRequest(
            "offer details are required when creating a job offer"
        )
    if status == "offered" and offer is None:
        raise BadRequest("offer details are required for offered status")
    if (
        status == application["status"]
        and not interview_provided
        and not offer_provided
    ):
        event_id = application.get("notificationEventId")
        if event_id:
            enqueue_application_status_push(
                db,
                application,
                event_id,
            )
        return jsonify(
            {"jobApplication": serialize_job_application(application)}
        )
    if (
        status != application["status"]
        and status
        not in APPLICATION_STATUS_TRANSITIONS[application["status"]]
    ):
        raise Conflict(
            f"Application cannot move from {application['status']} to {status}"
        )

    note = _optional_text(payload, "note", 1000)
    if interview_provided and interview is None:
        if application.get("interview") is None:
            return jsonify(
                {
                    "jobApplication": serialize_job_application(
                        application
                    )
                }
            )
        if not note:
            note = "Görüşme planı kaldırıldı."
    elif interview is not None and not note:
        note = "Görüşme planı güncellendi."
    if offer is not None and not note:
        note = "İş teklifi oluşturuldu."
    reservation = None
    reservation_created = False
    if status in {"offered", "hired"} and application.get("jobPostingId"):
        posting = db.jobPostings.find_one(
            {
                "_id": application["jobPostingId"],
                "employerKey": employer_key,
            }
        )
        if posting is not None:
            reservation, reservation_created = _reserve_hiring_slot(
                db,
                posting,
                application,
                now,
            )

    notification_event_id = uuid4().hex
    history_item = {
        "status": status,
        "note": note,
        "changedAt": now,
    }
    updates = {
        "status": status,
        "notificationEventId": notification_event_id,
        "updatedAt": now,
    }
    if reservation is not None:
        updates["hiringSlot"] = reservation["slot"]
    if interview is not None:
        updates["interview"] = interview
    if offer is not None:
        updates["offer"] = offer
    update_operation = {
        "$set": updates,
        "$push": {"statusHistory": history_item},
    }
    if interview_provided and interview is None:
        update_operation["$unset"] = {"interview": ""}
    try:
        result = db.jobApplications.update_one(
            {
                "_id": application["_id"],
                "status": application["status"],
            },
            update_operation,
        )
    except Exception:
        if reservation_created:
            db.jobHiringSlots.delete_one(
                {"applicationId": application["_id"]}
            )
        raise
    if result.modified_count != 1:
        if reservation_created:
            db.jobHiringSlots.delete_one(
                {"applicationId": application["_id"]}
            )
        raise Conflict("Application status changed concurrently")
    if (
        application.get("status") == "offered"
        and status not in {"offered", "hired"}
    ):
        _release_application_hiring_slot(db, application["_id"])
    updated = db.jobApplications.find_one({"_id": application["_id"]})
    push_options = {}
    if interview_provided:
        push_options = {
            "title": "Görüşme planınız güncellendi",
            "body": (
                "Görüşme tarihi ve detayları uygulamada "
                "güncellendi."
                if interview is not None
                else "Planlanan görüşmeniz kaldırıldı."
            ),
        }
    enqueue_application_status_push(
        db,
        updated,
        notification_event_id,
        **push_options,
    )
    return jsonify({"jobApplication": serialize_job_application(updated)})


def _get_user(user_id: str) -> dict:
    if not ObjectId.is_valid(user_id):
        raise BadRequest("Invalid user id")

    user = get_db().users.find_one({"_id": ObjectId(user_id)})
    if user is None:
        raise NotFound("User not found")
    return user


def _job_snapshot(recommendation: dict) -> dict:
    return {
        "jobPostingId": (
            str(recommendation["jobPostingId"])
            if recommendation.get("jobPostingId")
            else None
        ),
        "title": recommendation.get("title"),
        "company": recommendation.get("company"),
        "location": recommendation.get("location"),
        "requiredSkills": recommendation.get("requiredSkills", []),
        "matchScore": recommendation.get("matchScore"),
        "reason": recommendation.get("reason"),
    }


def _candidate_snapshot(user: dict, profile: dict | None) -> dict:
    return {
        "name": user.get("name") or (profile or {}).get("name") or "",
        "phone": user.get("phone"),
        "profileStatus": user.get("profileStatus"),
        "skills": (profile or {}).get("skills", []),
        "summary": (profile or {}).get("summary"),
    }


def _optional_text(payload: dict, field: str, maximum: int) -> str:
    value = payload.get(field, "")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise BadRequest(f"{field} must be a string")
    value = value.strip()
    if len(value) > maximum:
        raise BadRequest(
            f"{field} cannot exceed {maximum} characters"
        )
    return value


def _parse_interview(
    payload: dict,
    now: datetime,
) -> dict | None:
    if "interview" not in payload:
        return None
    value = payload["interview"]
    if value is None:
        return None
    if not isinstance(value, dict):
        raise BadRequest("interview must be an object or null")

    scheduled_at_value = value.get("scheduledAt")
    if (
        not isinstance(scheduled_at_value, str)
        or not scheduled_at_value.strip()
    ):
        raise BadRequest("interview.scheduledAt is required")
    try:
        scheduled_at = datetime.fromisoformat(
            scheduled_at_value.strip().replace("Z", "+00:00")
        )
    except ValueError as error:
        raise BadRequest(
            "interview.scheduledAt must be an ISO 8601 date-time"
        ) from error
    if scheduled_at.tzinfo is None:
        raise BadRequest(
            "interview.scheduledAt must include a timezone"
        )
    scheduled_at = scheduled_at.astimezone(UTC)
    if scheduled_at <= now:
        raise BadRequest(
            "interview.scheduledAt must be in the future"
        )

    interview_type = value.get("type")
    if interview_type not in INTERVIEW_TYPES:
        raise BadRequest("Invalid interview type")
    location = _optional_text(value, "location", 300)
    if interview_type == "onsite" and not location:
        raise BadRequest(
            "interview.location is required for onsite interviews"
        )
    return {
        "scheduledAt": scheduled_at,
        "type": interview_type,
        "location": location,
        "note": _optional_text(value, "note", 1000),
        "updatedAt": now,
    }


def _parse_offer(
    payload: dict,
    now: datetime,
) -> dict | None:
    if "offer" not in payload:
        return None
    value = payload["offer"]
    if not isinstance(value, dict):
        raise BadRequest("offer must be an object")

    start_date = _parse_offer_datetime(value, "startDate")
    expires_at = _parse_offer_datetime(value, "expiresAt")
    if start_date <= now:
        raise BadRequest("offer.startDate must be in the future")
    if expires_at <= now:
        raise BadRequest("offer.expiresAt must be in the future")
    if expires_at >= start_date:
        raise BadRequest("offer.expiresAt must be before offer.startDate")
    return {
        "startDate": start_date,
        "expiresAt": expires_at,
        "note": _optional_text(value, "note", 1000),
        "updatedAt": now,
    }


def _parse_offer_datetime(value: dict, field: str) -> datetime:
    raw_value = value.get(field)
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise BadRequest(f"offer.{field} is required")
    try:
        parsed = datetime.fromisoformat(
            raw_value.strip().replace("Z", "+00:00")
        )
    except ValueError as error:
        raise BadRequest(
            f"offer.{field} must be an ISO 8601 date-time"
        ) from error
    if parsed.tzinfo is None:
        raise BadRequest(f"offer.{field} must include a timezone")
    return parsed.astimezone(UTC)


def _pagination(page: int, limit: int, total: int) -> dict:
    return {
        "page": page,
        "limit": limit,
        "total": total,
        "pages": (total + limit - 1) // limit,
    }


def _reserve_hiring_slot(
    db, posting: dict, application: dict, now: datetime
) -> tuple[dict, bool]:
    _release_expired_offer_slots(db, posting["_id"], now)
    existing = db.jobHiringSlots.find_one(
        {"applicationId": application["_id"]}
    )
    if existing is not None:
        return existing, False

    _backfill_hiring_slots(db, posting, now)
    for slot in range(1, posting.get("openings", 1) + 1):
        document = {
            "jobPostingId": posting["_id"],
            "applicationId": application["_id"],
            "slot": slot,
            "createdAt": now,
        }
        try:
            result = db.jobHiringSlots.insert_one(document)
            document["_id"] = result.inserted_id
            return document, True
        except DuplicateKeyError:
            existing = db.jobHiringSlots.find_one(
                {"applicationId": application["_id"]}
            )
            if existing is not None:
                return existing, False

    raise Conflict("Job posting hiring capacity has been reached")


def _backfill_hiring_slots(
    db, posting: dict, now: datetime
) -> None:
    hired_applications = db.jobApplications.find(
        {
            "jobPostingId": posting["_id"],
            "$or": [
                {"status": "hired"},
                {
                    "status": "offered",
                    "offer.expiresAt": {"$gt": now},
                },
            ],
        }
    ).sort("createdAt", 1)
    for hired_application in hired_applications:
        if db.jobHiringSlots.find_one(
            {"applicationId": hired_application["_id"]}
        ):
            continue
        for slot in range(1, posting.get("openings", 1) + 1):
            try:
                db.jobHiringSlots.insert_one(
                    {
                        "jobPostingId": posting["_id"],
                        "applicationId": hired_application["_id"],
                        "slot": slot,
                        "createdAt": now,
                    }
                )
                break
            except DuplicateKeyError:
                if db.jobHiringSlots.find_one(
                    {
                        "applicationId": hired_application[
                            "_id"
                        ]
                    }
                ):
                    break


def _release_expired_offer_slots(
    db,
    job_posting_id: ObjectId,
    now: datetime,
) -> None:
    expired_ids = [
        item["_id"]
        for item in db.jobApplications.find(
            {
                "jobPostingId": job_posting_id,
                "status": "offered",
                "offer.expiresAt": {"$lte": now},
            },
            {"_id": 1},
        )
    ]
    if not expired_ids:
        return
    db.jobHiringSlots.delete_many(
        {"applicationId": {"$in": expired_ids}}
    )
    db.jobApplications.update_many(
        {"_id": {"$in": expired_ids}},
        {"$unset": {"hiringSlot": ""}},
    )


def _release_application_hiring_slot(
    db,
    application_id: ObjectId,
) -> None:
    db.jobHiringSlots.delete_one({"applicationId": application_id})
    db.jobApplications.update_one(
        {"_id": application_id},
        {"$unset": {"hiringSlot": ""}},
    )
