from bson import ObjectId
from flask import Blueprint, current_app, jsonify
from werkzeug.exceptions import BadRequest, NotFound

from app.auth import require_worker
from app.db import get_db
from app.serializers import (
    serialize_job_application,
    serialize_job_recommendation,
    serialize_profile,
    serialize_transcript,
    serialize_user,
    serialize_video,
    serialize_worker_question,
    serialize_worker_support_hub,
)
from app.services.consents import (
    get_video_consent_record,
    serialize_worker_consent,
)
from app.services.video_processing import refresh_user_job_recommendations
from app.services.worker_support import build_worker_hub


dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.get("/api/users/<user_id>/dashboard")
@require_worker
def get_dashboard(user_id: str):
    if not ObjectId.is_valid(user_id):
        raise BadRequest("Invalid user id")

    db = get_db()
    user = db.users.find_one({"_id": ObjectId(user_id)})
    if user is None:
        raise NotFound("User not found")

    latest_video = None
    latest_transcript = None
    latest_video_id = user.get("latestVideoId")
    if latest_video_id:
        latest_video = db.videos.find_one({"_id": latest_video_id})
        latest_transcript = db.videoTranscripts.find_one({"videoId": latest_video_id})

    profile = (
        db.candidateProfiles.find_one(
            {
                "userId": user["_id"],
                "latestVideoId": latest_video_id,
            }
        )
        if latest_video_id
        else None
    )
    recommendation_video = None
    if profile and profile.get("latestVideoId"):
        recommendation_video = db.videos.find_one(
            {"_id": profile["latestVideoId"]}
        )
    if profile and recommendation_video:
        refresh_user_job_recommendations(
            db, user, recommendation_video, profile
        )
    recommendations = list(
        db.jobRecommendations.find(
            {
                "userId": user["_id"],
                "videoId": latest_video_id,
            }
        )
        .sort("matchScore", -1)
        .limit(10)
    )
    recommendation_ids = [item["_id"] for item in recommendations]
    posting_ids = [
        item["jobPostingId"]
        for item in recommendations
        if item.get("jobPostingId")
    ]
    application_query = [
        {"jobRecommendationId": {"$in": recommendation_ids}}
    ]
    if posting_ids:
        application_query.append(
            {"jobPostingId": {"$in": posting_ids}}
        )
    application_documents = list(
        db.jobApplications.find(
            {
                "userId": user["_id"],
                "$or": application_query,
            }
        )
    )
    recent_applications = list(
        db.jobApplications.find({"userId": user["_id"]})
        .sort("updatedAt", -1)
        .limit(20)
    )
    applications_by_recommendation = {
        item["jobRecommendationId"]: item
        for item in application_documents
    }
    applications_by_posting = {
        item["jobPostingId"]: item
        for item in application_documents
        if item.get("jobPostingId")
    }
    recent_questions = list(
        db.workerQuestions.find({"userId": user["_id"]})
        .sort("createdAt", -1)
        .limit(5)
    )
    pending_question_count = db.workerQuestions.count_documents(
        {"userId": user["_id"], "status": "pending"}
    )
    consent_version = current_app.config.get(
        "VIDEO_CONSENT_VERSION", ""
    )
    video_consent = get_video_consent_record(
        db,
        user["_id"],
        consent_version,
    )

    return jsonify(
        {
            "user": serialize_user(user),
            "latestVideo": serialize_video(latest_video) if latest_video else None,
            "latestTranscript": serialize_transcript(latest_transcript) if latest_transcript else None,
            "candidateProfile": serialize_profile(profile) if profile else None,
            "recommendedJobs": [
                serialize_job_recommendation(
                    item,
                    applications_by_recommendation.get(item["_id"])
                    or applications_by_posting.get(
                        item.get("jobPostingId")
                    ),
                )
                for item in recommendations
            ],
            "jobApplications": [
                serialize_job_application(item)
                for item in recent_applications
            ],
            "workerHub": serialize_worker_support_hub(build_worker_hub(db, user)),
            "videoConsent": serialize_worker_consent(
                video_consent,
                version=consent_version,
                policy_url=current_app.config.get(
                    "PRIVACY_POLICY_URL", ""
                ),
            ),
            "recentQuestions": [serialize_worker_question(item) for item in recent_questions],
            "pendingQuestionCount": pending_question_count,
        }
    )
