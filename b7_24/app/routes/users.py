from datetime import UTC, datetime

from bson import ObjectId
from flask import Blueprint, current_app, jsonify, request
from pymongo.errors import DuplicateKeyError
from werkzeug.exceptions import BadRequest, Conflict, NotFound, Unauthorized

from app.auth import require_worker
from app.db import get_db
from app.serializers import serialize_user
from app.serializers import serialize_profile
from app.services.account_deletion import delete_worker_account
from app.services.consents import (
    accept_video_consent,
    get_video_consent_record,
    revoke_video_consent,
    serialize_worker_consent,
)
from app.services.data_export import build_worker_data_export
from app.validation import require_json_fields


users_bp = Blueprint("users", __name__)


@users_bp.post("/api/users")
def create_user():
    if current_app.config.get("AUTH_REQUIRED", True):
        raise Unauthorized("Use phone verification to create a user")
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise BadRequest("Request body must be a JSON object")
    unknown_fields = set(payload) - {"phone", "employerKey"}
    if unknown_fields:
        raise BadRequest(
            "Unknown registration fields: "
            + ", ".join(sorted(unknown_fields))
        )
    require_json_fields(payload, ["phone"])

    now = datetime.now(UTC)
    user = {
        "name": "",
        "nameStatus": "pending_video",
        "profileReviewStatus": "pending_video",
        "phone": payload["phone"].strip(),
        "employerKey": payload.get("employerKey", "default").strip() if payload.get("employerKey") else "default",
        "profileStatus": "registered",
        "videoStatus": "not_uploaded",
        "latestVideoId": None,
        "createdAt": now,
        "updatedAt": now,
    }

    if not user["phone"]:
        raise BadRequest("phone cannot be empty")

    try:
        result = get_db().users.insert_one(user)
    except DuplicateKeyError as exc:
        raise Conflict("A user with this phone number already exists") from exc

    user["_id"] = result.inserted_id
    return jsonify({"user": serialize_user(user)}), 201


@users_bp.get("/api/users/<user_id>")
@require_worker
def get_user(user_id: str):
    if not ObjectId.is_valid(user_id):
        raise BadRequest("Invalid user id")

    user = get_db().users.find_one({"_id": ObjectId(user_id)})
    if user is None:
        raise NotFound("User not found")

    return jsonify({"user": serialize_user(user)})


@users_bp.put("/api/users/<user_id>/profile-review")
@require_worker
def review_user_profile(user_id: str):
    if not ObjectId.is_valid(user_id):
        raise BadRequest("Invalid user id")
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise BadRequest("Request body must be a JSON object")
    unknown_fields = set(payload) - {"name"}
    if unknown_fields:
        raise BadRequest(
            "Unknown profile review fields: "
            + ", ".join(sorted(unknown_fields))
        )
    require_json_fields(payload, ["name"])
    name = _normalize_person_name(payload["name"])

    db = get_db()
    user_object_id = ObjectId(user_id)
    user = db.users.find_one({"_id": user_object_id})
    if user is None:
        raise NotFound("User not found")
    latest_video_id = user.get("latestVideoId")
    if (
        user.get("profileStatus") != "profile_ready"
        or user.get("videoStatus") != "completed"
        or latest_video_id is None
    ):
        raise Conflict("Profile is not ready for review")
    profile = db.candidateProfiles.find_one(
        {
            "userId": user_object_id,
            "latestVideoId": latest_video_id,
        }
    )
    if profile is None:
        raise Conflict("Profile is not ready for review")

    current_name = " ".join(
        (user.get("name") or profile.get("name") or "").split()
    )
    same_name = current_name.casefold() == name.casefold()
    previous_name_status = user.get("nameStatus")
    name_status = (
        "corrected_by_worker"
        if (
            previous_name_status == "corrected_by_worker"
            or not same_name
        )
        else "confirmed_by_worker"
    )
    now = datetime.now(UTC)
    result = db.users.update_one(
        {
            "_id": user_object_id,
            "latestVideoId": latest_video_id,
            "updatedAt": user.get("updatedAt"),
        },
        {
            "$set": {
                "name": name,
                "nameStatus": name_status,
                "profileReviewStatus": "confirmed",
                "profileReviewedAt": now,
                "updatedAt": now,
            }
        },
    )
    if result.modified_count != 1:
        raise Conflict("Profile changed concurrently")
    profile_result = db.candidateProfiles.update_one(
        {
            "_id": profile["_id"],
            "latestVideoId": latest_video_id,
        },
        {
            "$set": {
                "name": name,
                "nameSource": "worker_review",
                "nameReviewedAt": now,
                "updatedAt": now,
            }
        },
    )
    if profile_result.matched_count != 1:
        raise Conflict("Profile changed concurrently")
    db.jobApplications.update_many(
        {"userId": user_object_id},
        {
            "$set": {
                "candidate.name": name,
                "candidate.profileStatus": "profile_ready",
                "candidateUpdatedAt": now,
            }
        },
    )
    updated_user = db.users.find_one({"_id": user_object_id})
    updated_profile = db.candidateProfiles.find_one(
        {"_id": profile["_id"]}
    )
    return jsonify(
        {
            "user": serialize_user(updated_user),
            "candidateProfile": serialize_profile(updated_profile),
        }
    )


@users_bp.get("/api/users/<user_id>/consents/video-processing")
@require_worker
def get_video_processing_consent(user_id: str):
    user_object_id = _require_existing_user(user_id)
    version = current_app.config["VIDEO_CONSENT_VERSION"]
    consent = get_video_consent_record(
        get_db(),
        user_object_id,
        version,
    )
    return jsonify(
        {
            "consent": serialize_worker_consent(
                consent,
                version=version,
                policy_url=current_app.config["PRIVACY_POLICY_URL"],
            )
        }
    )


@users_bp.put("/api/users/<user_id>/consents/video-processing")
@require_worker
def accept_video_processing_consent(user_id: str):
    user_object_id = _require_existing_user(user_id)
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise BadRequest("Request body must be a JSON object")
    unknown_fields = set(payload) - {"version", "accepted"}
    if unknown_fields:
        raise BadRequest(
            "Unknown consent fields: "
            + ", ".join(sorted(unknown_fields))
        )
    require_json_fields(payload, ["version", "accepted"])
    if payload["accepted"] is not True:
        raise BadRequest("accepted must be true")
    version = payload["version"]
    if not isinstance(version, str):
        raise BadRequest("version must be a string")
    version = version.strip()
    current_version = current_app.config["VIDEO_CONSENT_VERSION"]
    if version != current_version:
        raise Conflict("Consent version is no longer current")

    consent = accept_video_consent(
        get_db(),
        user_id=user_object_id,
        version=current_version,
        policy_url=current_app.config["PRIVACY_POLICY_URL"],
        app_version_code=request.headers.get("X-App-Version-Code"),
        app_version_name=request.headers.get("X-App-Version-Name"),
    )
    return jsonify(
        {
            "consent": serialize_worker_consent(
                consent,
                version=current_version,
                policy_url=current_app.config["PRIVACY_POLICY_URL"],
            )
        }
    )


@users_bp.delete("/api/users/<user_id>/consents/video-processing")
@require_worker
def withdraw_video_processing_consent(user_id: str):
    user_object_id = _require_existing_user(user_id)
    version = current_app.config["VIDEO_CONSENT_VERSION"]
    consent = revoke_video_consent(
        get_db(),
        user_id=user_object_id,
        version=version,
    )
    return jsonify(
        {
            "consent": serialize_worker_consent(
                consent,
                version=version,
                policy_url=current_app.config["PRIVACY_POLICY_URL"],
            )
        }
    )


@users_bp.delete("/api/users/<user_id>")
@require_worker
def delete_user(user_id: str):
    if not ObjectId.is_valid(user_id):
        raise BadRequest("Invalid user id")

    delete_worker_account(
        get_db(),
        ObjectId(user_id),
        current_app.config["UPLOAD_FOLDER"],
        current_app.config[
            "ACCOUNT_DELETION_AUDIT_RETENTION_DAYS"
        ],
    )
    return current_app.response_class(status=204)


@users_bp.get("/api/users/<user_id>/data-export")
@require_worker
def export_user_data(user_id: str):
    if not ObjectId.is_valid(user_id):
        raise BadRequest("Invalid user id")

    user = get_db().users.find_one({"_id": ObjectId(user_id)})
    if user is None:
        raise NotFound("User not found")
    response = jsonify(build_worker_data_export(get_db(), user))
    response.headers["Content-Disposition"] = (
        f'attachment; filename="worker-data-{user_id}.json"'
    )
    return response


@users_bp.get("/api/users")
def find_users():
    if current_app.config.get("AUTH_REQUIRED", True):
        raise Unauthorized("Phone lookup is not available without authentication")
    phone = request.args.get("phone")
    if not phone:
        raise BadRequest("phone query parameter is required")

    user = get_db().users.find_one({"phone": phone.strip()})
    if user is None:
        raise NotFound("User not found")

    return jsonify({"user": serialize_user(user)})


def _normalize_person_name(value) -> str:
    if not isinstance(value, str):
        raise BadRequest("name must be a string")
    name = " ".join(value.split())
    if not 2 <= len(name) <= 100:
        raise BadRequest(
            "name must contain between 2 and 100 characters"
        )
    if sum(character.isalpha() for character in name) < 2:
        raise BadRequest("name must contain letters")
    allowed_punctuation = {" ", "-", "'", "’", "."}
    if any(
        not character.isalpha()
        and character not in allowed_punctuation
        for character in name
    ):
        raise BadRequest("name contains unsupported characters")
    return name


def _require_existing_user(user_id: str) -> ObjectId:
    if not ObjectId.is_valid(user_id):
        raise BadRequest("Invalid user id")
    user_object_id = ObjectId(user_id)
    if get_db().users.find_one({"_id": user_object_id}) is None:
        raise NotFound("User not found")
    return user_object_id
