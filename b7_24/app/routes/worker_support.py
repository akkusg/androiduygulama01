from datetime import UTC, datetime
from uuid import uuid4

from bson import ObjectId
from flask import Blueprint, current_app, jsonify, request
from pymongo import ReturnDocument
from werkzeug.exceptions import BadRequest, Conflict, NotFound

from app.auth import (
    get_current_principal,
    require_employer,
    require_worker,
)
from app.db import get_db
from app.serializers import (
    serialize_assessment_result,
    serialize_shuttle_request,
    serialize_training_progress,
    serialize_worker_question,
    serialize_worker_support_config,
    serialize_worker_support_hub,
)
from app.services.rate_limit import consume_action_rate_limit
from app.services.push_notifications import (
    enqueue_question_answered_push,
    enqueue_shuttle_status_push,
)
from app.services.idempotency import idempotent_worker_action
from app.services.worker_config import (
    create_worker_config_item,
    delete_worker_config_item,
    normalize_worker_config_patch,
    update_shuttle_settings,
    update_worker_config_item,
)
from app.services.worker_support import (
    answer_worker_question,
    build_worker_hub,
    cancel_shuttle_request,
    complete_assessment,
    complete_training,
    get_or_create_worker_support_config,
    request_shuttle,
    save_training_progress,
    upsert_worker_support_config,
)
from app.validation import parse_pagination, require_json_fields


worker_support_bp = Blueprint("worker_support", __name__)

SHUTTLE_REQUEST_STATUSES = {"requested", "confirmed", "rejected"}
SHUTTLE_FILTER_STATUSES = {
    *SHUTTLE_REQUEST_STATUSES,
    "cancelled",
    "replaced",
}
SHUTTLE_STATUS_TRANSITIONS = {
    "requested": {"confirmed", "rejected"},
    "confirmed": {"rejected"},
    "rejected": {"confirmed"},
}
QUESTION_STATUSES = {"pending", "answered", "auto_answered"}


@worker_support_bp.get("/api/users/<user_id>/worker-hub")
@require_worker
def get_worker_hub(user_id: str):
    user = _get_user(user_id)
    return jsonify({"workerHub": serialize_worker_support_hub(build_worker_hub(get_db(), user))})


@worker_support_bp.post("/api/users/<user_id>/questions")
@require_worker
@idempotent_worker_action
def ask_worker_question(user_id: str):
    user = _get_user(user_id)
    payload = _get_json_object()
    require_json_fields(payload, ["question"])
    if not isinstance(payload["question"], str):
        raise BadRequest("question must be a string")
    question = payload["question"].strip()
    if not question:
        raise BadRequest("question cannot be empty")
    if len(question) > 2000:
        raise BadRequest("question cannot exceed 2000 characters")

    db = get_db()
    consume_action_rate_limit(
        db,
        scope="worker-question",
        subject=user_id,
        maximum=current_app.config.get(
            "WORKER_QUESTION_MAX_REQUESTS", 20
        ),
        window_seconds=current_app.config.get(
            "WORKER_QUESTION_RATE_LIMIT_WINDOW_SECONDS", 3600
        ),
        message="Question limit reached",
    )
    answer = answer_worker_question(db, user, question)
    return jsonify({"answer": serialize_worker_question(answer)}), 201


@worker_support_bp.get(
    "/api/employers/<employer_key>/questions"
)
@require_employer
def list_employer_questions(employer_key: str):
    status = request.args.get("status")
    if status and status not in QUESTION_STATUSES:
        raise BadRequest("Invalid question status")

    page, limit = parse_pagination(request.args)
    query = {"employerKey": employer_key}
    if status:
        query["status"] = status
    db = get_db()
    total = db.workerQuestions.count_documents(query)
    questions = list(
        db.workerQuestions.find(query)
        .sort("createdAt", -1)
        .skip((page - 1) * limit)
        .limit(limit)
    )
    user_ids = list(
        {
            item["userId"]
            for item in questions
            if item.get("userId")
        }
    )
    users = {
        user["_id"]: user
        for user in db.users.find({"_id": {"$in": user_ids}})
    }
    return jsonify(
        {
            "questions": [
                {
                    **serialize_worker_question(item),
                    "worker": _serialize_shuttle_worker(
                        users.get(item.get("userId"))
                    ),
                }
                for item in questions
            ],
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "pages": (total + limit - 1) // limit,
            },
        }
    )


@worker_support_bp.patch(
    "/api/employers/<employer_key>/questions/<question_id>"
)
@require_employer
def answer_employer_question(
    employer_key: str, question_id: str
):
    if not ObjectId.is_valid(question_id):
        raise BadRequest("Invalid question id")
    payload = _get_json_object()
    require_json_fields(payload, ["answer"])
    answer = payload["answer"]
    if not isinstance(answer, str):
        raise BadRequest("answer must be a string")
    answer = answer.strip()
    if not answer:
        raise BadRequest("answer cannot be empty")
    if len(answer) > 5000:
        raise BadRequest("answer cannot exceed 5000 characters")

    db = get_db()
    existing = db.workerQuestions.find_one(
        {
            "_id": ObjectId(question_id),
            "employerKey": employer_key,
        }
    )
    if existing is None:
        raise NotFound("Question not found")
    if (
        existing.get("status") == "answered"
        and existing.get("answer") == answer
    ):
        event_id = existing.get("notificationEventId")
        if event_id:
            enqueue_question_answered_push(
                db,
                existing,
                event_id,
            )
        return jsonify(
            {"question": serialize_worker_question(existing)}
        )

    now = datetime.now(UTC)
    notification_event_id = uuid4().hex
    principal = (
        get_current_principal()
        if current_app.config.get("AUTH_REQUIRED", True)
        else {}
    )
    updated = db.workerQuestions.find_one_and_update(
        {
            "_id": ObjectId(question_id),
            "employerKey": employer_key,
            "updatedAt": existing.get("updatedAt"),
        },
        {
            "$set": {
                "answer": answer,
                "status": "answered",
                "answeredBy": principal.get("username"),
                "answeredAt": now,
                "notificationEventId": notification_event_id,
                "updatedAt": now,
            }
        },
        return_document=ReturnDocument.AFTER,
    )
    if updated is None:
        raise Conflict("Question changed concurrently")
    enqueue_question_answered_push(
        db,
        updated,
        notification_event_id,
    )
    return jsonify(
        {"question": serialize_worker_question(updated)}
    )


@worker_support_bp.post("/api/users/<user_id>/assessments/<assessment_id>/complete")
@require_worker
@idempotent_worker_action
def complete_user_assessment(user_id: str, assessment_id: str):
    user = _get_user(user_id)
    payload = _get_json_object()
    result = complete_assessment(get_db(), user, assessment_id, payload)
    if result is None:
        raise NotFound("Assessment not found")
    return jsonify({"assessment": serialize_assessment_result(result)}), 201


@worker_support_bp.post("/api/users/<user_id>/trainings/<training_id>/complete")
@require_worker
@idempotent_worker_action
def complete_user_training(user_id: str, training_id: str):
    user = _get_user(user_id)
    payload = _get_json_object()
    progress = complete_training(get_db(), user, training_id, payload)
    if progress is None:
        raise NotFound("Training not found")
    return jsonify({"training": serialize_training_progress(progress)}), 201


@worker_support_bp.put(
    "/api/users/<user_id>/trainings/<training_id>/progress"
)
@require_worker
@idempotent_worker_action
def save_user_training_progress(user_id: str, training_id: str):
    user = _get_user(user_id)
    payload = _get_json_object()
    progress = save_training_progress(
        get_db(),
        user,
        training_id,
        payload,
    )
    if progress is None:
        raise NotFound("Training not found")
    return jsonify(
        {"training": serialize_training_progress(progress)}
    )


@worker_support_bp.post("/api/users/<user_id>/shuttle-requests")
@require_worker
@idempotent_worker_action
def request_user_shuttle(user_id: str):
    user = _get_user(user_id)
    payload = _get_json_object()
    require_json_fields(payload, ["routeId"])
    route_id = payload["routeId"]
    if not isinstance(route_id, str) or not route_id.strip():
        raise BadRequest("routeId must be a non-empty string")
    pickup_note = payload.get("pickupNote", "")
    if not isinstance(pickup_note, str):
        raise BadRequest("pickupNote must be a string")
    pickup_note = pickup_note.strip()
    if len(pickup_note) > 500:
        raise BadRequest("pickupNote cannot exceed 500 characters")
    shuttle_request = request_shuttle(
        get_db(),
        user,
        route_id=route_id.strip(),
        pickup_note=pickup_note,
    )
    if shuttle_request is None:
        raise NotFound("Shuttle route not found")
    return jsonify({"shuttleRequest": serialize_shuttle_request(shuttle_request)}), 201


@worker_support_bp.post(
    "/api/users/<user_id>/shuttle-requests/<request_id>/cancel"
)
@require_worker
@idempotent_worker_action
def cancel_user_shuttle_request(user_id: str, request_id: str):
    if not ObjectId.is_valid(request_id):
        raise BadRequest("Invalid shuttle request id")
    user = _get_user(user_id)
    shuttle_request = cancel_shuttle_request(
        get_db(),
        user,
        request_id,
    )
    if shuttle_request is None:
        raise NotFound("Shuttle request not found")
    return jsonify(
        {"shuttleRequest": serialize_shuttle_request(shuttle_request)}
    )


@worker_support_bp.get("/api/employers/<employer_key>/shuttle-requests")
@require_employer
def list_employer_shuttle_requests(employer_key: str):
    status = request.args.get("status")
    if status and status not in SHUTTLE_FILTER_STATUSES:
        raise BadRequest("Invalid shuttle request status")

    query = {"employerKey": employer_key}
    if status:
        query["status"] = status

    page, limit = parse_pagination(request.args)
    db = get_db()
    total = db.workerShuttleRequests.count_documents(query)
    requests = list(
        db.workerShuttleRequests.find(query)
        .sort("createdAt", -1)
        .skip((page - 1) * limit)
        .limit(limit)
    )
    user_ids = list(
        {item["userId"] for item in requests if item.get("userId")}
    )
    users = {
        user["_id"]: user
        for user in db.users.find({"_id": {"$in": user_ids}})
    }
    return jsonify(
        {
            "shuttleRequests": [
                {
                    **serialize_shuttle_request(item),
                    "worker": _serialize_shuttle_worker(
                        users.get(item.get("userId"))
                    ),
                }
                for item in requests
            ],
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "pages": (total + limit - 1) // limit,
            },
        }
    )


@worker_support_bp.patch("/api/employers/<employer_key>/shuttle-requests/<request_id>")
@require_employer
def update_employer_shuttle_request(employer_key: str, request_id: str):
    if not ObjectId.is_valid(request_id):
        raise BadRequest("Invalid shuttle request id")

    payload = _get_json_object()
    require_json_fields(payload, ["status"])
    status = payload["status"]
    if status not in SHUTTLE_REQUEST_STATUSES:
        raise BadRequest("Invalid shuttle request status")

    db = get_db()
    shuttle_request = db.workerShuttleRequests.find_one(
        {"_id": ObjectId(request_id), "employerKey": employer_key}
    )
    if shuttle_request is None:
        raise NotFound("Shuttle request not found")
    if status == shuttle_request["status"]:
        event_id = shuttle_request.get("notificationEventId")
        if event_id:
            enqueue_shuttle_status_push(
                db,
                shuttle_request,
                event_id,
            )
        return jsonify(
            {"shuttleRequest": serialize_shuttle_request(shuttle_request)}
        )
    if status not in SHUTTLE_STATUS_TRANSITIONS.get(
        shuttle_request["status"], set()
    ):
        raise BadRequest(
            "Invalid shuttle request status transition"
        )

    decision_note = payload.get("decisionNote", "")
    if decision_note is None:
        decision_note = ""
    if not isinstance(decision_note, str):
        raise BadRequest("decisionNote must be a string")
    decision_note = decision_note.strip()
    if len(decision_note) > 1000:
        raise BadRequest(
            "decisionNote cannot exceed 1000 characters"
        )

    notification_event_id = uuid4().hex
    db.workerShuttleRequests.update_one(
        {"_id": shuttle_request["_id"]},
        {
            "$set": {
                "status": status,
                "decisionNote": decision_note,
                "notificationEventId": notification_event_id,
                "updatedAt": datetime.now(UTC),
            }
        },
    )
    updated = db.workerShuttleRequests.find_one({"_id": shuttle_request["_id"]})
    enqueue_shuttle_status_push(
        db,
        updated,
        notification_event_id,
    )
    return jsonify({"shuttleRequest": serialize_shuttle_request(updated)})


@worker_support_bp.get("/api/employers/<employer_key>/worker-config")
@require_employer
def get_employer_worker_config(employer_key: str):
    config = get_or_create_worker_support_config(get_db(), employer_key)
    return jsonify({"workerConfig": serialize_worker_support_config(config)})


@worker_support_bp.put("/api/employers/<employer_key>/worker-config")
@require_employer
def update_employer_worker_config(employer_key: str):
    payload = normalize_worker_config_patch(_get_json_object())
    config = upsert_worker_support_config(get_db(), employer_key, payload)
    return jsonify({"workerConfig": serialize_worker_support_config(config)})


@worker_support_bp.post(
    "/api/employers/<employer_key>/worker-config/<resource>"
)
@require_employer
def create_employer_worker_config_item(employer_key: str, resource: str):
    db = get_db()
    config = get_or_create_worker_support_config(db, employer_key)
    item, updated = create_worker_config_item(
        db, config, resource, _get_json_object()
    )
    return (
        jsonify(
            {
                "item": item,
                "workerConfig": serialize_worker_support_config(updated),
            }
        ),
        201,
    )


@worker_support_bp.patch(
    "/api/employers/<employer_key>/worker-config/<resource>/<item_id>"
)
@require_employer
def update_employer_worker_config_item(
    employer_key: str, resource: str, item_id: str
):
    db = get_db()
    config = get_or_create_worker_support_config(db, employer_key)
    item, updated = update_worker_config_item(
        db, config, resource, item_id, _get_json_object()
    )
    return jsonify(
        {
            "item": item,
            "workerConfig": serialize_worker_support_config(updated),
        }
    )


@worker_support_bp.delete(
    "/api/employers/<employer_key>/worker-config/<resource>/<item_id>"
)
@require_employer
def delete_employer_worker_config_item(
    employer_key: str, resource: str, item_id: str
):
    db = get_db()
    config = get_or_create_worker_support_config(db, employer_key)
    updated = delete_worker_config_item(
        db, config, resource, item_id
    )
    return jsonify(
        {
            "deletedId": item_id,
            "workerConfig": serialize_worker_support_config(updated),
        }
    )


@worker_support_bp.patch(
    "/api/employers/<employer_key>/worker-config/shuttle"
)
@require_employer
def update_employer_shuttle_settings(employer_key: str):
    db = get_db()
    config = get_or_create_worker_support_config(db, employer_key)
    updated = update_shuttle_settings(db, config, _get_json_object())
    return jsonify({"workerConfig": serialize_worker_support_config(updated)})


@worker_support_bp.post(
    "/api/employers/<employer_key>/worker-config/shuttle/routes"
)
@require_employer
def create_employer_shuttle_route(employer_key: str):
    return _create_shuttle_route(employer_key)


@worker_support_bp.patch(
    "/api/employers/<employer_key>/worker-config/shuttle/routes/<route_id>"
)
@require_employer
def update_employer_shuttle_route(employer_key: str, route_id: str):
    db = get_db()
    config = get_or_create_worker_support_config(db, employer_key)
    item, updated = update_worker_config_item(
        db,
        config,
        "shuttle-routes",
        route_id,
        _get_json_object(),
    )
    return jsonify(
        {
            "item": item,
            "workerConfig": serialize_worker_support_config(updated),
        }
    )


@worker_support_bp.delete(
    "/api/employers/<employer_key>/worker-config/shuttle/routes/<route_id>"
)
@require_employer
def delete_employer_shuttle_route(employer_key: str, route_id: str):
    db = get_db()
    config = get_or_create_worker_support_config(db, employer_key)
    updated = delete_worker_config_item(
        db, config, "shuttle-routes", route_id
    )
    return jsonify(
        {
            "deletedId": route_id,
            "workerConfig": serialize_worker_support_config(updated),
        }
    )


def _create_shuttle_route(employer_key: str):
    db = get_db()
    config = get_or_create_worker_support_config(db, employer_key)
    item, updated = create_worker_config_item(
        db, config, "shuttle-routes", _get_json_object()
    )
    return (
        jsonify(
            {
                "item": item,
                "workerConfig": serialize_worker_support_config(updated),
            }
        ),
        201,
    )


def _get_user(user_id: str) -> dict:
    if not ObjectId.is_valid(user_id):
        raise BadRequest("Invalid user id")

    user = get_db().users.find_one({"_id": ObjectId(user_id)})
    if user is None:
        raise NotFound("User not found")
    return user


def _serialize_shuttle_worker(user: dict | None) -> dict | None:
    if user is None:
        return None
    return {
        "id": str(user["_id"]),
        "name": user.get("name") or "",
        "phone": user.get("phone") or "",
    }


def _get_json_object() -> dict:
    payload = request.get_json(silent=True)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise BadRequest("Request body must be a JSON object")
    return payload
