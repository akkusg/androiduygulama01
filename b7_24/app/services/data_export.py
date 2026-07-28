from datetime import UTC, datetime

from app.serializers import (
    serialize_assessment_result,
    serialize_job_application,
    serialize_job_recommendation,
    serialize_profile,
    serialize_shuttle_request,
    serialize_training_progress,
    serialize_transcript,
    serialize_user,
    serialize_video,
    serialize_worker_question,
)
from app.services.consents import serialize_worker_consent


def build_worker_data_export(db, user: dict) -> dict:
    user_id = user["_id"]
    profile = db.candidateProfiles.find_one({"userId": user_id})
    support_assignment = db.workerSupportAssignments.find_one(
        {"userId": user_id}
    )
    return {
        "schemaVersion": 2,
        "exportedAt": datetime.now(UTC).isoformat(),
        "user": serialize_user(user),
        "consents": [
            serialize_worker_consent(
                item,
                version=item.get("version", ""),
                policy_url=item.get("policyUrl", ""),
            )
            for item in db.workerConsents.find(
                {"userId": user_id}
            ).sort("createdAt", 1)
        ],
        "videos": [
            serialize_video(item)
            for item in db.videos.find(
                {"userId": user_id}
            ).sort("createdAt", 1)
        ],
        "transcripts": [
            serialize_transcript(item)
            for item in db.videoTranscripts.find(
                {"userId": user_id}
            ).sort("createdAt", 1)
        ],
        "candidateProfile": (
            serialize_profile(profile) if profile else None
        ),
        "jobRecommendations": [
            serialize_job_recommendation(item)
            for item in db.jobRecommendations.find(
                {"userId": user_id}
            ).sort("createdAt", 1)
        ],
        "jobApplications": [
            serialize_job_application(item)
            for item in db.jobApplications.find(
                {"userId": user_id}
            ).sort("createdAt", 1)
        ],
        "workerSupport": {
            "assignments": (
                {
                    "assessmentIds": support_assignment.get(
                        "assessmentIds", []
                    ),
                    "trainingIds": support_assignment.get(
                        "trainingIds", []
                    ),
                }
                if support_assignment
                else None
            ),
            "questions": [
                serialize_worker_question(item)
                for item in db.workerQuestions.find(
                    {"userId": user_id}
                ).sort("createdAt", 1)
            ],
            "assessments": [
                serialize_assessment_result(item)
                for item in db.workerAssessmentResults.find(
                    {"userId": user_id}
                ).sort("completedAt", 1)
            ],
            "trainings": [
                serialize_training_progress(item)
                for item in db.workerTrainingProgress.find(
                    {"userId": user_id}
                ).sort("completedAt", 1)
            ],
            "shuttleRequests": [
                serialize_shuttle_request(item)
                for item in db.workerShuttleRequests.find(
                    {"userId": user_id}
                ).sort("createdAt", 1)
            ],
        },
        "devices": [
            {
                "installationId": item.get("installationId"),
                "platform": item.get("platform"),
                "appVersionCode": item.get("appVersionCode"),
                "appVersionName": item.get("appVersionName"),
                "active": item.get("active", False),
                "lastSeenAt": (
                    item["lastSeenAt"].isoformat()
                    if item.get("lastSeenAt")
                    else None
                ),
            }
            for item in db.workerPushRegistrations.find(
                {"userId": user_id}
            ).sort("createdAt", 1)
        ],
    }
