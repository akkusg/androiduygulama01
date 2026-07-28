from bson import ObjectId
from flask import Blueprint, current_app, jsonify, request
from werkzeug.exceptions import BadRequest, NotFound

from app.auth import require_worker
from app.db import get_db
from app.services.push_notifications import (
    register_worker_device,
    serialize_worker_device,
    unregister_worker_device,
)


devices_bp = Blueprint("devices", __name__)


@devices_bp.put(
    "/api/users/<user_id>/devices/<installation_id>"
)
@require_worker
def register_user_device(
    user_id: str,
    installation_id: str,
):
    user = _get_user(user_id)
    payload = request.get_json(silent=True)
    device = register_worker_device(
        get_db(),
        user,
        installation_id,
        payload,
        current_app.config,
    )
    return jsonify({"device": serialize_worker_device(device)})


@devices_bp.delete(
    "/api/users/<user_id>/devices/<installation_id>"
)
@require_worker
def unregister_user_device(
    user_id: str,
    installation_id: str,
):
    user = _get_user(user_id)
    unregister_worker_device(
        get_db(),
        user,
        installation_id,
    )
    return current_app.response_class(status=204)


def _get_user(user_id: str) -> dict:
    if not ObjectId.is_valid(user_id):
        raise BadRequest("Invalid user id")
    user = get_db().users.find_one({"_id": ObjectId(user_id)})
    if user is None:
        raise NotFound("User not found")
    return user
