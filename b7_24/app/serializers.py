from datetime import datetime

from bson import ObjectId


def serialize_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def serialize_object_id(value: ObjectId | None) -> str | None:
    return str(value) if value else None


def serialize_user(user: dict) -> dict:
    name_status = user.get("nameStatus", "pending_video")
    if name_status in {
        "provided",
        "confirmed_by_worker",
        "corrected_by_worker",
    }:
        profile_review_status = "confirmed"
    elif name_status == "inferred_from_video":
        profile_review_status = "pending"
    else:
        profile_review_status = "pending_video"
    return {
        "id": serialize_object_id(user.get("_id")),
        "name": user.get("name"),
        "nameStatus": name_status,
        "profileReviewStatus": profile_review_status,
        "profileReviewedAt": serialize_datetime(
            user.get("profileReviewedAt")
        ),
        "phone": user.get("phone"),
        "employerKey": user.get("employerKey", "default"),
        "phoneVerifiedAt": serialize_datetime(user.get("phoneVerifiedAt")),
        "profileStatus": user.get("profileStatus"),
        "videoStatus": user.get("videoStatus"),
        "latestVideoId": serialize_object_id(user.get("latestVideoId")),
        "createdAt": serialize_datetime(user.get("createdAt")),
        "updatedAt": serialize_datetime(user.get("updatedAt")),
    }


def serialize_video(video: dict) -> dict:
    return {
        "id": serialize_object_id(video.get("_id")),
        "userId": serialize_object_id(video.get("userId")),
        "originalFilename": video.get("originalFilename"),
        "contentType": video.get("contentType"),
        "status": video.get("status"),
        "sourceDeletionStatus": video.get("sourceDeletionStatus"),
        "sourceDeletedAt": serialize_datetime(video.get("sourceDeletedAt")),
        "processingError": video.get("processingError"),
        "nextRetryAt": serialize_datetime(video.get("nextRetryAt")),
        "consentVersion": video.get("consentVersion"),
        "consentAcceptedAt": serialize_datetime(
            video.get("consentAcceptedAt")
        ),
        "createdAt": serialize_datetime(video.get("createdAt")),
        "updatedAt": serialize_datetime(video.get("updatedAt")),
    }


def serialize_profile(profile: dict) -> dict:
    return {
        "userId": serialize_object_id(profile.get("userId")),
        "latestVideoId": serialize_object_id(profile.get("latestVideoId")),
        "name": profile.get("name"),
        "nameSource": profile.get("nameSource"),
        "nameReviewedAt": serialize_datetime(
            profile.get("nameReviewedAt")
        ),
        "summary": profile.get("summary"),
        "skills": profile.get("skills", []),
        "preferredRoles": profile.get("preferredRoles", []),
        "availability": profile.get("availability"),
        "confidence": profile.get("confidence"),
        "warnings": profile.get("warnings", []),
        "createdAt": serialize_datetime(profile.get("createdAt")),
        "updatedAt": serialize_datetime(profile.get("updatedAt")),
    }


def serialize_transcript(transcript: dict) -> dict:
    return {
        "id": serialize_object_id(transcript.get("_id")),
        "videoId": serialize_object_id(transcript.get("videoId")),
        "userId": serialize_object_id(transcript.get("userId")),
        "provider": transcript.get("provider"),
        "status": transcript.get("status"),
        "text": transcript.get("text"),
        "segments": transcript.get("segments", []),
        "metadata": transcript.get("metadata", {}),
        "warnings": transcript.get("warnings", []),
        "createdAt": serialize_datetime(transcript.get("createdAt")),
        "updatedAt": serialize_datetime(transcript.get("updatedAt")),
    }


def serialize_job_recommendation(recommendation: dict, application: dict | None = None) -> dict:
    return {
        "id": serialize_object_id(recommendation.get("_id")),
        "userId": serialize_object_id(recommendation.get("userId")),
        "videoId": serialize_object_id(recommendation.get("videoId")),
        "jobPostingId": serialize_object_id(
            recommendation.get("jobPostingId")
        ),
        "title": recommendation.get("title"),
        "company": recommendation.get("company"),
        "location": recommendation.get("location"),
        "requiredSkills": recommendation.get("requiredSkills", []),
        "matchScore": recommendation.get("matchScore"),
        "reason": recommendation.get("reason"),
        "applicationId": serialize_object_id(application.get("_id")) if application else None,
        "applicationStatus": application.get("status") if application else "not_applied",
        "appliedAt": serialize_datetime(application.get("createdAt")) if application else None,
        "createdAt": serialize_datetime(recommendation.get("createdAt")),
        "updatedAt": serialize_datetime(recommendation.get("updatedAt")),
    }


def serialize_job_posting(posting: dict) -> dict:
    return {
        "id": serialize_object_id(posting.get("_id")),
        "employerKey": posting.get("employerKey"),
        "title": posting.get("title"),
        "company": posting.get("company"),
        "location": posting.get("location"),
        "description": posting.get("description"),
        "requiredSkills": posting.get("requiredSkills", []),
        "optionalSkills": posting.get("optionalSkills", []),
        "status": posting.get("status"),
        "employmentType": posting.get("employmentType"),
        "shift": posting.get("shift"),
        "openings": posting.get("openings"),
        "publishedAt": serialize_datetime(posting.get("publishedAt")),
        "createdAt": serialize_datetime(posting.get("createdAt")),
        "updatedAt": serialize_datetime(posting.get("updatedAt")),
    }


def serialize_job_application(application: dict) -> dict:
    interview = application.get("interview")
    return {
        "id": serialize_object_id(application.get("_id")),
        "userId": serialize_object_id(application.get("userId")),
        "jobRecommendationId": serialize_object_id(application.get("jobRecommendationId")),
        "jobPostingId": serialize_object_id(
            application.get("jobPostingId")
        ),
        "employerKey": application.get("employerKey"),
        "status": application.get("status"),
        "coverNote": application.get("coverNote"),
        "hiringSlot": application.get("hiringSlot"),
        "interview": (
            {
                **interview,
                "scheduledAt": serialize_datetime(
                    interview.get("scheduledAt")
                ),
                "updatedAt": serialize_datetime(
                    interview.get("updatedAt")
                ),
            }
            if interview
            else None
        ),
        "withdrawnAt": serialize_datetime(
            application.get("withdrawnAt")
        ),
        "job": application.get("job", {}),
        "candidate": application.get("candidate", {}),
        "statusHistory": [
            {
                **item,
                "changedAt": serialize_datetime(item.get("changedAt")),
            }
            for item in application.get("statusHistory", [])
        ],
        "createdAt": serialize_datetime(application.get("createdAt")),
        "updatedAt": serialize_datetime(application.get("updatedAt")),
    }


def serialize_worker_support_hub(hub: dict) -> dict:
    return {
        "employerKey": hub.get("employerKey"),
        "assessments": hub.get("assessments", []),
        "trainings": hub.get("trainings", []),
        "usefulInfo": hub.get("usefulInfo", []),
        "shuttle": hub.get("shuttle", {}),
    }


def serialize_worker_support_config(config: dict) -> dict:
    return {
        "id": serialize_object_id(config.get("_id")),
        "employerKey": config.get("employerKey"),
        "schemaVersion": config.get("schemaVersion"),
        "assessments": config.get("assessments", []),
        "trainings": config.get("trainings", []),
        "usefulInfo": config.get("usefulInfo", []),
        "shuttle": config.get("shuttle", {}),
        "qaKnowledgeBase": config.get("qaKnowledgeBase", []),
        "createdAt": serialize_datetime(config.get("createdAt")),
        "updatedAt": serialize_datetime(config.get("updatedAt")),
    }


def serialize_worker_support_assignments(assignments: dict) -> dict:
    return {
        "workerId": assignments.get("workerId"),
        "employerKey": assignments.get("employerKey"),
        "customized": assignments.get("customized", False),
        "assessmentIds": assignments.get("assessmentIds", []),
        "trainingIds": assignments.get("trainingIds", []),
        "catalog": assignments.get(
            "catalog",
            {"assessments": [], "trainings": []},
        ),
        "createdAt": serialize_datetime(assignments.get("createdAt")),
        "updatedAt": serialize_datetime(assignments.get("updatedAt")),
    }


def serialize_worker_question(question: dict) -> dict:
    return {
        "id": serialize_object_id(question.get("_id")),
        "userId": serialize_object_id(question.get("userId")),
        "employerKey": question.get("employerKey"),
        "question": question.get("question"),
        "answer": question.get("answer"),
        "status": question.get("status")
        or ("answered" if question.get("answer") else "pending"),
        "matchedKeywords": question.get("matchedKeywords", []),
        "answeredBy": question.get("answeredBy"),
        "answeredAt": serialize_datetime(question.get("answeredAt")),
        "createdAt": serialize_datetime(question.get("createdAt")),
        "updatedAt": serialize_datetime(question.get("updatedAt")),
    }


def serialize_assessment_result(result: dict) -> dict:
    return {
        "id": serialize_object_id(result.get("_id")),
        "userId": serialize_object_id(result.get("userId")),
        "assessmentId": result.get("assessmentId"),
        "title": result.get("title"),
        "status": result.get("status"),
        "score": result.get("score"),
        "passScore": result.get("passScore"),
        "passed": result.get("passed"),
        "answers": result.get("answers", []),
        "attemptCount": result.get("attemptCount", 1),
        "attemptHistory": [
            {
                **attempt,
                "completedAt": serialize_datetime(
                    attempt.get("completedAt")
                ),
            }
            for attempt in result.get("attemptHistory", [])
        ],
        "completedAt": serialize_datetime(result.get("completedAt")),
    }


def serialize_training_progress(progress: dict) -> dict:
    return {
        "id": serialize_object_id(progress.get("_id")),
        "userId": serialize_object_id(progress.get("userId")),
        "trainingId": progress.get("trainingId"),
        "title": progress.get("title"),
        "status": progress.get("status"),
        "progressPercent": progress.get("progressPercent"),
        "completedModules": progress.get("completedModules", []),
        "completedAt": serialize_datetime(progress.get("completedAt")),
    }


def serialize_shuttle_request(request: dict) -> dict:
    return {
        "id": serialize_object_id(request.get("_id")),
        "userId": serialize_object_id(request.get("userId")),
        "routeId": request.get("routeId"),
        "routeName": request.get("routeName"),
        "pickupWindow": request.get("pickupWindow"),
        "pickupNote": request.get("pickupNote"),
        "status": request.get("status"),
        "decisionNote": request.get("decisionNote"),
        "cancelledAt": serialize_datetime(
            request.get("cancelledAt")
        ),
        "createdAt": serialize_datetime(request.get("createdAt")),
        "updatedAt": serialize_datetime(request.get("updatedAt")),
    }
