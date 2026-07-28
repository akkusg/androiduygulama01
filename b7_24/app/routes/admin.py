from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from bson import ObjectId
from flask import Blueprint, current_app, jsonify, render_template, request
from pymongo.errors import DuplicateKeyError
from werkzeug.exceptions import BadRequest, Conflict, NotFound

from app.auth import get_current_principal, require_employer
from app.db import get_db
from app.serializers import (
    serialize_assessment_result,
    serialize_job_application,
    serialize_profile,
    serialize_shuttle_request,
    serialize_training_progress,
    serialize_user,
    serialize_worker_question,
    serialize_worker_support_assignments,
)
from app.services.account_deletion import delete_worker_account
from app.services.data_hygiene import (
    build_worker_data_hygiene_record,
    correct_invalid_worker_phone,
    legacy_worker_cleanup_allowed,
)
from app.services.worker_support import (
    build_worker_support_assignments,
    get_or_create_worker_support_config,
    save_worker_support_assignments,
)
from app.services.auth import VALID_STORED_PHONE, normalize_phone
from app.services.consents import (
    get_video_consent_record,
    serialize_worker_consent,
)
from app.services.video_processing import requeue_failed_video_job
from app.validation import parse_pagination


admin_bp = Blueprint("admin", __name__)


@admin_bp.get("/admin")
def admin_panel():
    return render_template("admin.html")


@admin_bp.get("/api/admin/overview")
@require_employer
def admin_overview():
    principal = get_current_principal()
    employer_key = principal["employerKey"]
    db = get_db()
    now = datetime.now(UTC)
    config = get_or_create_worker_support_config(db, employer_key)

    application_counts = _status_counts(
        db.jobApplications, {"employerKey": employer_key}
    )
    shuttle_counts = _status_counts(
        db.workerShuttleRequests, {"employerKey": employer_key}
    )
    worker_ids = db.users.distinct(
        "_id",
        {"employerKey": employer_key},
    )
    worker_scope = {"userId": {"$in": worker_ids}}
    video_processing_counts = _status_counts(
        db.videoProcessingJobs,
        worker_scope,
    )
    push_notification_counts = _status_counts(
        db.pushNotificationJobs,
        worker_scope,
    )
    video_worker_filter = {
        "status": "running",
        "expiresAt": {"$gt": now},
    }
    push_worker_filter = {
        "status": "running",
        "expiresAt": {"$gt": now},
    }
    video_worker_runtime = _latest_worker_runtime(
        db.videoWorkerHeartbeats,
        video_worker_filter,
        (
            "transcriptionProvider",
            "transcriptionModel",
            "modelWarmed",
        ),
    )
    push_worker_runtime = _latest_worker_runtime(
        db.pushWorkerHeartbeats,
        push_worker_filter,
        (
            "provider",
            "projectId",
            "credentialsValidated",
        ),
    )
    recent_applications = list(
        db.jobApplications.find({"employerKey": employer_key})
        .sort("createdAt", -1)
        .limit(5)
    )
    recent_shuttle_requests = list(
        db.workerShuttleRequests.find({"employerKey": employer_key})
        .sort("createdAt", -1)
        .limit(5)
    )

    return jsonify(
        {
            "employerKey": employer_key,
            "metrics": {
                "workers": db.users.count_documents(
                    {"employerKey": employer_key}
                ),
                "publishedJobPostings": db.jobPostings.count_documents(
                    {
                        "employerKey": employer_key,
                        "status": "published",
                    }
                ),
                "pendingInvitations": db.workerInvitations.count_documents(
                    {
                        "employerKey": employer_key,
                        "status": "pending",
                        "expiresAt": {"$gt": now},
                    }
                ),
                "applications": sum(application_counts.values()),
                "openApplications": sum(
                    application_counts.get(status, 0)
                    for status in ("submitted", "reviewing", "shortlisted")
                ),
                "pendingShuttleRequests": shuttle_counts.get("requested", 0),
                "completedAssessments": db.workerAssessmentResults.count_documents(
                    {"employerKey": employer_key, "status": "completed"}
                ),
                "completedTrainings": db.workerTrainingProgress.count_documents(
                    {"employerKey": employer_key, "status": "completed"}
                ),
                "pendingQuestions": db.workerQuestions.count_documents(
                    {"employerKey": employer_key, "status": "pending"}
                ),
                "invalidPhoneWorkers": db.users.count_documents(
                    {
                        "employerKey": employer_key,
                        "phone": {"$not": VALID_STORED_PHONE},
                    }
                ),
            },
            "applicationCounts": application_counts,
            "shuttleCounts": shuttle_counts,
            "contentCounts": {
                "assessments": len(config.get("assessments", [])),
                "trainings": len(config.get("trainings", [])),
                "usefulInfo": len(config.get("usefulInfo", [])),
                "qaKnowledgeBase": len(config.get("qaKnowledgeBase", [])),
                "shuttleRoutes": len(
                    (config.get("shuttle") or {}).get("routes", [])
                ),
            },
            "operations": {
                "videoProcessing": {
                    "activeWorkers": db.videoWorkerHeartbeats.count_documents(
                        video_worker_filter
                    ),
                    "runtime": video_worker_runtime,
                    "queue": _normalized_counts(
                        video_processing_counts,
                        ("queued", "processing", "completed", "failed"),
                    ),
                },
                "pushNotifications": {
                    "provider": current_app.config.get(
                        "PUSH_PROVIDER",
                        "disabled",
                    ),
                    "activeWorkers": db.pushWorkerHeartbeats.count_documents(
                        push_worker_filter
                    ),
                    "runtime": push_worker_runtime,
                    "queue": _normalized_counts(
                        push_notification_counts,
                        (
                            "queued",
                            "processing",
                            "sent",
                            "skipped",
                            "failed",
                        ),
                    ),
                },
                "videoSourceDeletionFailures": db.videos.count_documents(
                    {
                        **worker_scope,
                        "sourceDeletionStatus": "failed",
                    }
                ),
            },
            "recentApplications": [
                serialize_job_application(item)
                for item in recent_applications
            ],
            "recentShuttleRequests": [
                serialize_shuttle_request(item)
                for item in recent_shuttle_requests
            ],
        }
    )


@admin_bp.get("/api/employers/<employer_key>/workers")
@require_employer
def list_employer_workers(employer_key: str):
    try:
        page = max(1, int(request.args.get("page", "1")))
        limit = min(100, max(1, int(request.args.get("limit", "25"))))
    except ValueError as error:
        raise BadRequest("page and limit must be integers") from error

    query: dict = {"employerKey": employer_key}
    search = request.args.get("search", "").strip()
    if search:
        if len(search) > 100:
            raise BadRequest("search cannot exceed 100 characters")
        pattern = re.compile(re.escape(search), re.IGNORECASE)
        query["$or"] = [{"name": pattern}, {"phone": pattern}]

    db = get_db()
    total = db.users.count_documents(query)
    users = list(
        db.users.find(query)
        .sort("createdAt", -1)
        .skip((page - 1) * limit)
        .limit(limit)
    )
    user_ids = [user["_id"] for user in users]
    profiles = {
        profile["userId"]: profile
        for profile in db.candidateProfiles.find(
            {"userId": {"$in": user_ids}}
        )
    }
    application_counts = {
        item["_id"]: item["count"]
        for item in db.jobApplications.aggregate(
            [
                {"$match": {"userId": {"$in": user_ids}}},
                {"$group": {"_id": "$userId", "count": {"$sum": 1}}},
            ]
        )
    }

    return jsonify(
        {
            "workers": [
                {
                    **serialize_user(user),
                    "profile": (
                        serialize_profile(profiles[user["_id"]])
                        if (
                            user["_id"] in profiles
                            and profiles[user["_id"]].get(
                                "latestVideoId"
                            )
                            == user.get("latestVideoId")
                        )
                        else None
                    ),
                    "applicationCount": application_counts.get(
                        user["_id"], 0
                    ),
                }
                for user in users
            ],
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "pages": (total + limit - 1) // limit,
            },
        }
    )


@admin_bp.get(
    "/api/employers/<employer_key>/data-hygiene/workers"
)
@require_employer
def list_invalid_phone_workers(employer_key: str):
    page, limit = parse_pagination(
        request.args,
        default_limit=25,
        maximum_limit=100,
    )
    query = {
        "employerKey": employer_key,
        "phone": {"$not": VALID_STORED_PHONE},
    }
    db = get_db()
    total = db.users.count_documents(query)
    workers = list(
        db.users.find(query)
        .sort("createdAt", -1)
        .skip((page - 1) * limit)
        .limit(limit)
    )
    return jsonify(
        {
            "workers": [
                {
                    **serialize_user(worker),
                    **build_worker_data_hygiene_record(db, worker),
                }
                for worker in workers
            ],
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "pages": (total + limit - 1) // limit,
            },
        }
    )


@admin_bp.patch(
    "/api/employers/<employer_key>/data-hygiene/workers/"
    "<worker_id>/phone"
)
@require_employer
def correct_invalid_phone_worker(
    employer_key: str,
    worker_id: str,
):
    worker = _get_employer_worker(employer_key, worker_id)
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise BadRequest("Request body must be a JSON object")
    corrected = correct_invalid_worker_phone(
        get_db(),
        worker,
        payload.get("phone"),
    )
    return jsonify({"worker": serialize_user(corrected)})


@admin_bp.delete(
    "/api/employers/<employer_key>/data-hygiene/workers/"
    "<worker_id>"
)
@require_employer
def cleanup_invalid_phone_worker(
    employer_key: str,
    worker_id: str,
):
    worker = _get_employer_worker(employer_key, worker_id)
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or payload.get(
        "confirmation"
    ) != "TEMIZLE":
        raise BadRequest("confirmation must be TEMIZLE")
    db = get_db()
    if not legacy_worker_cleanup_allowed(db, worker):
        raise Conflict(
            "Only unverified legacy workers without sessions or videos "
            "can be cleaned up"
        )
    delete_worker_account(
        db,
        worker["_id"],
        current_app.config["UPLOAD_FOLDER"],
        current_app.config[
            "ACCOUNT_DELETION_AUDIT_RETENTION_DAYS"
        ],
    )
    return current_app.response_class(status=204)


@admin_bp.get(
    "/api/employers/<employer_key>/video-processing-jobs"
)
@require_employer
def list_video_processing_jobs(employer_key: str):
    page, limit = parse_pagination(
        request.args,
        default_limit=25,
        maximum_limit=100,
    )
    status = request.args.get("status", "failed").strip()
    allowed_statuses = {
        "queued",
        "processing",
        "completed",
        "failed",
    }
    if status and status not in allowed_statuses:
        raise BadRequest("Invalid video processing job status")

    db = get_db()
    worker_ids = db.users.distinct(
        "_id",
        {"employerKey": employer_key},
    )
    query: dict = {"userId": {"$in": worker_ids}}
    if status:
        query["status"] = status
    total = db.videoProcessingJobs.count_documents(query)
    jobs = list(
        db.videoProcessingJobs.find(query)
        .sort("updatedAt", -1)
        .skip((page - 1) * limit)
        .limit(limit)
    )
    job_worker_ids = list(
        {
            job["userId"]
            for job in jobs
            if isinstance(job.get("userId"), ObjectId)
        }
    )
    workers = {
        worker["_id"]: worker
        for worker in db.users.find(
            {"_id": {"$in": job_worker_ids}}
        )
    }
    video_ids = list(
        {
            job["videoId"]
            for job in jobs
            if isinstance(job.get("videoId"), ObjectId)
        }
    )
    videos = {
        video["_id"]: video
        for video in db.videos.find(
            {"_id": {"$in": video_ids}}
        )
    }

    return jsonify(
        {
            "videoProcessingJobs": [
                _serialize_video_processing_job(
                    job,
                    workers.get(job.get("userId")),
                    videos.get(job.get("videoId")),
                )
                for job in jobs
            ],
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "pages": (total + limit - 1) // limit,
            },
        }
    )


@admin_bp.post(
    "/api/employers/<employer_key>/video-processing-jobs/"
    "<job_id>/retry"
)
@require_employer
def retry_video_processing_job(employer_key: str, job_id: str):
    if not ObjectId.is_valid(job_id):
        raise BadRequest("Invalid video processing job id")

    db = get_db()
    job = db.videoProcessingJobs.find_one(
        {"_id": ObjectId(job_id)}
    )
    if job is None:
        raise NotFound("Video processing job not found")
    worker = db.users.find_one(
        {
            "_id": job.get("userId"),
            "employerKey": employer_key,
        }
    )
    if worker is None:
        raise NotFound("Video processing job not found")

    principal = get_current_principal()
    updated = requeue_failed_video_job(
        db,
        job,
        current_app.config,
        requested_by=principal.get("username") or "employer",
    )
    video = db.videos.find_one({"_id": updated["videoId"]})
    return jsonify(
        {
            "videoProcessingJob": _serialize_video_processing_job(
                updated,
                worker,
                video,
            )
        }
    )


@admin_bp.get(
    "/api/employers/<employer_key>/workers/<worker_id>"
)
@require_employer
def get_employer_worker_detail(employer_key: str, worker_id: str):
    if not ObjectId.is_valid(worker_id):
        raise BadRequest("Invalid worker id")

    db = get_db()
    worker_object_id = ObjectId(worker_id)
    worker = db.users.find_one(
        {
            "_id": worker_object_id,
            "employerKey": employer_key,
        }
    )
    if worker is None:
        raise NotFound("Worker not found")

    latest_video_id = worker.get("latestVideoId")
    profile = (
        db.candidateProfiles.find_one(
            {
                "userId": worker_object_id,
                "latestVideoId": latest_video_id,
            }
        )
        if latest_video_id
        else None
    )
    tenant_worker_query = {
        "userId": worker_object_id,
        "employerKey": employer_key,
    }
    assessment_results = list(
        db.workerAssessmentResults.find(tenant_worker_query).sort(
            "completedAt", -1
        )
    )
    training_progress = list(
        db.workerTrainingProgress.find(tenant_worker_query).sort(
            "completedAt", -1
        )
    )
    latest_shuttle_request = db.workerShuttleRequests.find_one(
        {
            **tenant_worker_query,
            "status": {
                "$in": [
                    "requested",
                    "confirmed",
                    "rejected",
                    "cancelled",
                    "completed",
                ]
            },
        },
        sort=[("updatedAt", -1)],
    )
    recent_questions = list(
        db.workerQuestions.find(tenant_worker_query)
        .sort("createdAt", -1)
        .limit(10)
    )
    applications = list(
        db.jobApplications.find(tenant_worker_query)
        .sort("createdAt", -1)
        .limit(25)
    )
    support_assignments = build_worker_support_assignments(
        db,
        worker,
    )
    consent_version = current_app.config.get(
        "VIDEO_CONSENT_VERSION", ""
    )
    video_consent = get_video_consent_record(
        db,
        worker_object_id,
        consent_version,
    )

    return jsonify(
        {
            "worker": serialize_user(worker),
            "profile": serialize_profile(profile) if profile else None,
            "videoConsent": serialize_worker_consent(
                video_consent,
                version=consent_version,
                policy_url=current_app.config.get(
                    "PRIVACY_POLICY_URL", ""
                ),
            ),
            "assessmentResults": [
                serialize_assessment_result(item)
                for item in assessment_results
            ],
            "trainingProgress": [
                serialize_training_progress(item)
                for item in training_progress
            ],
            "shuttleRequest": (
                serialize_shuttle_request(latest_shuttle_request)
                if latest_shuttle_request
                else None
            ),
            "recentQuestions": [
                serialize_worker_question(item)
                for item in recent_questions
            ],
            "applications": [
                serialize_job_application(item)
                for item in applications
            ],
            "supportAssignments": serialize_worker_support_assignments(
                support_assignments
            ),
        }
    )


@admin_bp.get(
    "/api/employers/<employer_key>/workers/<worker_id>/support-assignments"
)
@require_employer
def get_employer_worker_support_assignments(
    employer_key: str,
    worker_id: str,
):
    worker = _get_employer_worker(employer_key, worker_id)
    assignments = build_worker_support_assignments(get_db(), worker)
    return jsonify(
        {
            "supportAssignments": (
                serialize_worker_support_assignments(assignments)
            )
        }
    )


@admin_bp.put(
    "/api/employers/<employer_key>/workers/<worker_id>/support-assignments"
)
@require_employer
def update_employer_worker_support_assignments(
    employer_key: str,
    worker_id: str,
):
    worker = _get_employer_worker(employer_key, worker_id)
    payload = request.get_json(silent=True)
    principal = (
        get_current_principal()
        if current_app.config.get("AUTH_REQUIRED", True)
        else {}
    )
    assignments = save_worker_support_assignments(
        get_db(),
        worker,
        payload,
        assigned_by=principal.get("username"),
    )
    return jsonify(
        {
            "supportAssignments": (
                serialize_worker_support_assignments(assignments)
            )
        }
    )


@admin_bp.get("/api/employers/<employer_key>/worker-invitations")
@require_employer
def list_worker_invitations(employer_key: str):
    status = request.args.get("status", "pending")
    if status not in {"pending", "accepted", "cancelled", "expired"}:
        raise BadRequest("Invalid invitation status")

    now = datetime.now(UTC)
    db = get_db()
    if status == "pending":
        db.workerInvitations.update_many(
            {
                "employerKey": employer_key,
                "status": "pending",
                "expiresAt": {"$lte": now},
            },
            {"$set": {"status": "expired", "updatedAt": now}},
        )
    invitations = list(
        db.workerInvitations.find(
            {"employerKey": employer_key, "status": status}
        ).sort("createdAt", -1)
    )
    return jsonify(
        {
            "workerInvitations": [
                _serialize_worker_invitation(item)
                for item in invitations
            ]
        }
    )


@admin_bp.post("/api/employers/<employer_key>/worker-invitations")
@require_employer
def create_worker_invitation(employer_key: str):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise BadRequest("Request body must be a JSON object")
    phone = normalize_phone(payload.get("phone"))
    db = get_db()
    existing_user = db.users.find_one({"phone": phone})
    if (
        existing_user
        and (existing_user.get("employerKey") or "default") == employer_key
    ):
        raise Conflict("Worker already belongs to this employer")
    if (
        existing_user
        and (existing_user.get("employerKey") or "default")
        not in {"default", employer_key}
    ):
        raise Conflict("Worker belongs to another employer")
    if (
        existing_user
        and (existing_user.get("employerKey") or "default") == "default"
        and (
            existing_user.get("videoStatus", "not_uploaded") != "not_uploaded"
            or existing_user.get("profileStatus", "registered")
            != "registered"
        )
    ):
        raise Conflict("An active worker cannot be reassigned by invitation")

    now = datetime.now(UTC)
    db.workerInvitations.update_many(
        {
            "phone": phone,
            "status": "pending",
            "expiresAt": {"$lte": now},
        },
        {"$set": {"status": "expired", "updatedAt": now}},
    )
    expires_at = now + timedelta(
        days=current_app.config.get("WORKER_INVITATION_TTL_DAYS", 30)
    )
    principal = get_current_principal()
    invitation = {
        "phone": phone,
        "employerKey": employer_key,
        "status": "pending",
        "createdBy": principal.get("username"),
        "createdAt": now,
        "updatedAt": now,
        "expiresAt": expires_at,
        "purgeAt": expires_at + timedelta(days=90),
    }
    try:
        result = db.workerInvitations.insert_one(invitation)
    except DuplicateKeyError as error:
        raise Conflict("A pending invitation already exists for this phone") from error
    invitation["_id"] = result.inserted_id
    return jsonify(
        {"workerInvitation": _serialize_worker_invitation(invitation)}
    ), 201


@admin_bp.delete(
    "/api/employers/<employer_key>/worker-invitations/<invitation_id>"
)
@require_employer
def cancel_worker_invitation(
    employer_key: str, invitation_id: str
):
    if not ObjectId.is_valid(invitation_id):
        raise BadRequest("Invalid invitation id")
    now = datetime.now(UTC)
    db = get_db()
    result = db.workerInvitations.update_one(
        {
            "_id": ObjectId(invitation_id),
            "employerKey": employer_key,
            "status": "pending",
        },
        {"$set": {"status": "cancelled", "updatedAt": now}},
    )
    if result.modified_count != 1:
        raise NotFound("Pending invitation not found")
    invitation = db.workerInvitations.find_one(
        {"_id": ObjectId(invitation_id)}
    )
    return jsonify(
        {"workerInvitation": _serialize_worker_invitation(invitation)}
    )


@admin_bp.get("/api/employers/<employer_key>/audit-events")
@require_employer
def list_admin_audit_events(employer_key: str):
    page, limit = parse_pagination(request.args)
    outcome = request.args.get("outcome", "").strip()
    if outcome not in {"", "success", "rejected"}:
        raise BadRequest("Invalid audit outcome")

    query = {"employerKey": employer_key}
    if outcome:
        query["outcome"] = outcome

    db = get_db()
    total = db.adminAuditEvents.count_documents(query)
    events = list(
        db.adminAuditEvents.find(query)
        .sort("createdAt", -1)
        .skip((page - 1) * limit)
        .limit(limit)
    )
    return jsonify(
        {
            "auditEvents": [
                _serialize_admin_audit_event(event)
                for event in events
            ],
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "pages": (total + limit - 1) // limit,
            },
        }
    )


def _status_counts(collection, base_query: dict) -> dict[str, int]:
    return {
        item["_id"]: item["count"]
        for item in collection.aggregate(
            [
                {"$match": base_query},
                {"$group": {"_id": "$status", "count": {"$sum": 1}}},
            ]
        )
        if item["_id"]
    }


def _normalized_counts(
    counts: dict[str, int],
    statuses: tuple[str, ...],
) -> dict[str, int]:
    return {
        status: counts.get(status, 0)
        for status in statuses
    }


def _latest_worker_runtime(
    collection,
    active_filter: dict,
    fields: tuple[str, ...],
) -> dict | None:
    heartbeat = collection.find_one(
        active_filter,
        projection={field: 1 for field in (*fields, "updatedAt")},
        sort=[("updatedAt", -1)],
    )
    if heartbeat is None:
        return None
    return {
        **{field: heartbeat.get(field) for field in fields},
        "updatedAt": (
            heartbeat["updatedAt"].isoformat(timespec="milliseconds")
            if heartbeat.get("updatedAt")
            else None
        ),
    }


def _serialize_video_processing_job(
    job: dict,
    worker: dict | None,
    video: dict | None,
) -> dict:
    return {
        "id": str(job["_id"]),
        "videoId": str(job["videoId"]),
        "userId": str(job["userId"]),
        "status": job.get("status"),
        "attempts": job.get("attempts", 0),
        "maxAttempts": job.get("maxAttempts"),
        "lastError": job.get("lastError"),
        "manualRetryCount": job.get("manualRetryCount", 0),
        "availableAt": (
            job["availableAt"].isoformat()
            if job.get("availableAt")
            else None
        ),
        "failedAt": (
            job["failedAt"].isoformat()
            if job.get("failedAt")
            else None
        ),
        "createdAt": job["createdAt"].isoformat(),
        "updatedAt": job["updatedAt"].isoformat(),
        "worker": (
            {
                "id": str(worker["_id"]),
                "name": worker.get("name"),
                "phone": worker.get("phone"),
            }
            if worker
            else None
        ),
        "video": (
            {
                "id": str(video["_id"]),
                "originalFilename": video.get("originalFilename"),
                "sourceDeletionStatus": video.get(
                    "sourceDeletionStatus"
                ),
            }
            if video
            else None
        ),
    }


def _serialize_worker_invitation(invitation: dict) -> dict:
    return {
        "id": str(invitation["_id"]),
        "phone": invitation.get("phone"),
        "employerKey": invitation.get("employerKey"),
        "status": invitation.get("status"),
        "createdBy": invitation.get("createdBy"),
        "createdAt": invitation.get("createdAt").isoformat(),
        "expiresAt": invitation.get("expiresAt").isoformat(),
        "acceptedAt": (
            invitation.get("acceptedAt").isoformat()
            if invitation.get("acceptedAt")
            else None
        ),
    }


def _get_employer_worker(
    employer_key: str,
    worker_id: str,
) -> dict:
    if not ObjectId.is_valid(worker_id):
        raise BadRequest("Invalid worker id")
    worker = get_db().users.find_one(
        {
            "_id": ObjectId(worker_id),
            "employerKey": employer_key,
        }
    )
    if worker is None:
        raise NotFound("Worker not found")
    return worker


def _serialize_admin_audit_event(event: dict) -> dict:
    return {
        "id": str(event["_id"]),
        "employerKey": event.get("employerKey"),
        "username": event.get("username"),
        "method": event.get("method"),
        "action": event.get("action"),
        "target": event.get("target") or {},
        "statusCode": event.get("statusCode"),
        "outcome": event.get("outcome"),
        "authSource": event.get("authSource"),
        "requestId": event.get("requestId"),
        "createdAt": event.get("createdAt").isoformat(),
    }
