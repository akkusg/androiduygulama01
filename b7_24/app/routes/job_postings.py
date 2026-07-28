from __future__ import annotations

from datetime import UTC, datetime

from bson import ObjectId
from flask import Blueprint, jsonify, request
from werkzeug.exceptions import BadRequest, Conflict, NotFound

from app.auth import require_employer
from app.db import get_db
from app.serializers import serialize_job_posting


job_postings_bp = Blueprint("job_postings", __name__)

POSTING_STATUSES = {"draft", "published", "closed"}
EMPLOYMENT_TYPES = {"full_time", "part_time", "temporary", "contract"}
SHIFT_TYPES = {"day", "night", "rotating", "flexible"}


@job_postings_bp.get("/api/employers/<employer_key>/job-postings")
@require_employer
def list_job_postings(employer_key: str):
    status = request.args.get("status")
    if status and status not in POSTING_STATUSES:
        raise BadRequest("Invalid job posting status")
    try:
        page = max(1, int(request.args.get("page", "1")))
        limit = min(100, max(1, int(request.args.get("limit", "25"))))
    except ValueError as error:
        raise BadRequest("page and limit must be integers") from error

    query = {"employerKey": employer_key}
    if status:
        query["status"] = status
    db = get_db()
    total = db.jobPostings.count_documents(query)
    postings = list(
        db.jobPostings.find(query)
        .sort("createdAt", -1)
        .skip((page - 1) * limit)
        .limit(limit)
    )
    posting_ids = [item["_id"] for item in postings]
    application_counts = {
        item["_id"]: item["count"]
        for item in db.jobApplications.aggregate(
            [
                {"$match": {"jobPostingId": {"$in": posting_ids}}},
                {
                    "$group": {
                        "_id": "$jobPostingId",
                        "count": {"$sum": 1},
                    }
                },
            ]
        )
    }
    return jsonify(
        {
            "jobPostings": [
                {
                    **serialize_job_posting(item),
                    "applicationCount": application_counts.get(
                        item["_id"], 0
                    ),
                }
                for item in postings
            ],
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "pages": (total + limit - 1) // limit,
            },
        }
    )


@job_postings_bp.post("/api/employers/<employer_key>/job-postings")
@require_employer
def create_job_posting(employer_key: str):
    payload = _json_object()
    posting = _normalize_posting(payload, employer_key)
    now = datetime.now(UTC)
    posting.update(
        {
            "createdAt": now,
            "updatedAt": now,
            "publishedAt": (
                now if posting["status"] == "published" else None
            ),
        }
    )
    result = get_db().jobPostings.insert_one(posting)
    posting["_id"] = result.inserted_id
    return jsonify({"jobPosting": serialize_job_posting(posting)}), 201


@job_postings_bp.patch(
    "/api/employers/<employer_key>/job-postings/<posting_id>"
)
@require_employer
def update_job_posting(employer_key: str, posting_id: str):
    if not ObjectId.is_valid(posting_id):
        raise BadRequest("Invalid job posting id")
    payload = _json_object()
    if not payload:
        raise BadRequest("At least one job posting field is required")

    db = get_db()
    current = db.jobPostings.find_one(
        {"_id": ObjectId(posting_id), "employerKey": employer_key}
    )
    if current is None:
        raise NotFound("Job posting not found")

    merged = {
        key: value
        for key, value in current.items()
        if key
        not in {
            "_id",
            "employerKey",
            "createdAt",
            "updatedAt",
            "publishedAt",
        }
    }
    merged.update(payload)
    posting = _normalize_posting(merged, employer_key)
    if posting["openings"] < current.get("openings", 1):
        raise Conflict(
            "Job posting openings cannot be reduced"
        )
    now = datetime.now(UTC)
    updates = {**posting, "updatedAt": now}
    if (
        posting["status"] == "published"
        and current.get("status") != "published"
    ):
        updates["publishedAt"] = now
    if posting["status"] != "published":
        db.jobRecommendations.delete_many(
            {"jobPostingId": current["_id"]}
        )

    db.jobPostings.update_one(
        {"_id": current["_id"]}, {"$set": updates}
    )
    updated = db.jobPostings.find_one({"_id": current["_id"]})
    return jsonify({"jobPosting": serialize_job_posting(updated)})


@job_postings_bp.delete(
    "/api/employers/<employer_key>/job-postings/<posting_id>"
)
@require_employer
def delete_job_posting(employer_key: str, posting_id: str):
    if not ObjectId.is_valid(posting_id):
        raise BadRequest("Invalid job posting id")
    db = get_db()
    posting_id_value = ObjectId(posting_id)
    posting = db.jobPostings.find_one(
        {"_id": posting_id_value, "employerKey": employer_key}
    )
    if posting is None:
        raise NotFound("Job posting not found")
    if db.jobApplications.count_documents(
        {"jobPostingId": posting_id_value}
    ):
        raise Conflict(
            "A job posting with applications cannot be deleted; close it instead"
        )

    db.jobRecommendations.delete_many(
        {"jobPostingId": posting_id_value}
    )
    db.jobPostings.delete_one({"_id": posting_id_value})
    return "", 204


def _normalize_posting(payload: dict, employer_key: str) -> dict:
    allowed = {
        "title",
        "company",
        "location",
        "description",
        "requiredSkills",
        "optionalSkills",
        "status",
        "employmentType",
        "shift",
        "openings",
    }
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise BadRequest(
            f"Unknown job posting field(s): {', '.join(unknown)}"
        )

    required_skills = _skill_list(
        payload.get("requiredSkills"), "requiredSkills", required=True
    )
    optional_skills = _skill_list(
        payload.get("optionalSkills", []),
        "optionalSkills",
        required=False,
    )
    overlap = {
        skill.casefold() for skill in required_skills
    }.intersection(skill.casefold() for skill in optional_skills)
    if overlap:
        raise BadRequest(
            "optionalSkills cannot repeat requiredSkills"
        )

    openings = payload.get("openings", 1)
    if isinstance(openings, bool) or not isinstance(openings, int):
        raise BadRequest("openings must be an integer")
    if openings < 1 or openings > 10000:
        raise BadRequest("openings must be between 1 and 10000")

    status = payload.get("status", "draft")
    if status not in POSTING_STATUSES:
        raise BadRequest("Invalid job posting status")
    employment_type = payload.get("employmentType", "full_time")
    if employment_type not in EMPLOYMENT_TYPES:
        raise BadRequest("Invalid employment type")
    shift = payload.get("shift", "day")
    if shift not in SHIFT_TYPES:
        raise BadRequest("Invalid shift")

    return {
        "employerKey": employer_key,
        "title": _text(
            payload.get("title"), "title", 160, required=True
        ),
        "company": _text(
            payload.get("company", employer_key),
            "company",
            160,
            required=True,
        ),
        "location": _text(
            payload.get("location"), "location", 160, required=True
        ),
        "description": _text(
            payload.get("description"),
            "description",
            5000,
            required=True,
        ),
        "requiredSkills": required_skills,
        "optionalSkills": optional_skills,
        "status": status,
        "employmentType": employment_type,
        "shift": shift,
        "openings": openings,
    }


def _skill_list(value, field: str, *, required: bool) -> list[str]:
    if not isinstance(value, list):
        raise BadRequest(f"{field} must be an array")
    if required and not value:
        raise BadRequest(f"{field} must contain at least one skill")
    if len(value) > 30:
        raise BadRequest(f"{field} cannot contain more than 30 skills")

    result = []
    seen = set()
    for item in value:
        skill = _text(item, f"{field} item", 80, required=True)
        normalized = skill.casefold()
        if normalized not in seen:
            seen.add(normalized)
            result.append(skill)
    return result


def _text(value, field: str, maximum: int, *, required: bool) -> str:
    if not isinstance(value, str):
        raise BadRequest(f"{field} must be a string")
    normalized = value.strip()
    if required and not normalized:
        raise BadRequest(f"{field} cannot be empty")
    if len(normalized) > maximum:
        raise BadRequest(f"{field} cannot exceed {maximum} characters")
    return normalized


def _json_object() -> dict:
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise BadRequest("Request body must be a JSON object")
    return payload
