from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from functools import wraps
from uuid import uuid4

from flask import current_app, g, make_response, request
from pymongo.errors import DuplicateKeyError
from werkzeug.exceptions import BadRequest, Conflict

from app.db import get_db


IDEMPOTENCY_KEY_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$"
)
UPLOAD_SHA256_PATTERN = re.compile(r"^[A-Fa-f0-9]{64}$")


def idempotent_worker_action(view):
    return _idempotent_worker_request(
        view,
        fingerprint_builder=_request_fingerprint,
        timeout_config_key="IDEMPOTENCY_PROCESSING_TIMEOUT_SECONDS",
    )


def idempotent_worker_upload(view):
    return _idempotent_worker_request(
        view,
        fingerprint_builder=_upload_request_fingerprint,
        timeout_config_key=(
            "IDEMPOTENCY_UPLOAD_PROCESSING_TIMEOUT_SECONDS"
        ),
    )


def _idempotent_worker_request(
    view,
    *,
    fingerprint_builder,
    timeout_config_key: str,
):
    @wraps(view)
    def wrapped(*args, **kwargs):
        key = request.headers.get("Idempotency-Key", "").strip()
        required = current_app.config.get(
            "REQUIRE_IDEMPOTENCY_KEY", False
        )
        if not key:
            if required:
                raise BadRequest(
                    "Idempotency-Key header is required"
                )
            return view(*args, **kwargs)
        if not IDEMPOTENCY_KEY_PATTERN.fullmatch(key):
            raise BadRequest("Invalid Idempotency-Key header")

        subject = _worker_subject(kwargs)
        scope = f"{subject}:{request.method}:{request.endpoint}"
        request_hash = fingerprint_builder(kwargs)
        db = get_db()
        now = datetime.now(UTC)
        owner_id = uuid4().hex
        record = {
            "scope": scope,
            "idempotencyKey": key,
            "requestHash": request_hash,
            "status": "processing",
            "ownerId": owner_id,
            "createdAt": now,
            "updatedAt": now,
            "expiresAt": now
            + timedelta(
                seconds=current_app.config[timeout_config_key]
            ),
        }

        try:
            db.idempotencyRecords.insert_one(record)
        except DuplicateKeyError:
            existing = db.idempotencyRecords.find_one(
                {"scope": scope, "idempotencyKey": key}
            )
            if existing is None:
                raise
            if existing.get("requestHash") != request_hash:
                raise Conflict(
                    "Idempotency-Key was already used for another request"
                )
            if existing.get("status") == "completed":
                response = current_app.response_class(
                    response=existing.get("responseBody", ""),
                    status=existing.get("statusCode", 200),
                    content_type=existing.get(
                        "contentType", "application/json"
                    ),
                )
                response.headers["Idempotency-Replayed"] = "true"
                return response

            reclaimed = db.idempotencyRecords.update_one(
                {
                    "_id": existing["_id"],
                    "status": "processing",
                    "expiresAt": {"$lte": now},
                },
                {
                    "$set": {
                        "ownerId": owner_id,
                        "updatedAt": now,
                        "expiresAt": record["expiresAt"],
                    }
                },
            )
            if reclaimed.modified_count == 1:
                record["_id"] = existing["_id"]
            else:
                conflict = Conflict(
                    "A request with this Idempotency-Key is still processing"
                )
                conflict.retry_after = 1
                raise conflict

        try:
            response = make_response(view(*args, **kwargs))
            if response.status_code >= 500:
                db.idempotencyRecords.delete_one(
                    {"_id": record["_id"], "ownerId": owner_id}
                )
                return response

            completed_at = datetime.now(UTC)
            result = db.idempotencyRecords.update_one(
                {"_id": record["_id"], "ownerId": owner_id},
                {
                    "$set": {
                        "status": "completed",
                        "statusCode": response.status_code,
                        "contentType": response.content_type,
                        "responseBody": response.get_data(
                            as_text=True
                        ),
                        "updatedAt": completed_at,
                        "expiresAt": completed_at
                        + timedelta(
                            seconds=current_app.config[
                                "IDEMPOTENCY_RETENTION_SECONDS"
                            ]
                        ),
                    },
                    "$unset": {"ownerId": ""},
                },
            )
            if result.modified_count != 1:
                raise RuntimeError(
                    "Idempotency record ownership was lost"
                )
            response.headers["Idempotency-Replayed"] = "false"
            return response
        except Exception:
            db.idempotencyRecords.delete_one(
                {"_id": record["_id"], "ownerId": owner_id}
            )
            raise

    return wrapped


def _worker_subject(kwargs: dict) -> str:
    principal = getattr(g, "auth_session", None)
    principal_user_id = (
        principal.get("userId") if principal else None
    )
    return str(principal_user_id or kwargs.get("user_id") or "unknown")


def _request_fingerprint(kwargs: dict) -> str:
    payload = request.get_json(silent=True)
    if payload is None:
        serialized_payload = request.get_data(cache=True)
    else:
        serialized_payload = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    route_arguments = json.dumps(
        {
            key: str(value)
            for key, value in sorted(kwargs.items())
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    digest = hashlib.sha256()
    digest.update(route_arguments)
    digest.update(b"\0")
    digest.update(serialized_payload)
    return digest.hexdigest()


def _upload_request_fingerprint(kwargs: dict) -> str:
    upload_sha256 = request.headers.get(
        "X-Upload-SHA256", ""
    ).strip()
    if not UPLOAD_SHA256_PATTERN.fullmatch(upload_sha256):
        raise BadRequest(
            "X-Upload-SHA256 header must be a SHA-256 hex digest"
        )

    route_arguments = json.dumps(
        {
            key: str(value)
            for key, value in sorted(kwargs.items())
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    digest = hashlib.sha256()
    digest.update(route_arguments)
    digest.update(b"\0")
    digest.update(upload_sha256.lower().encode())
    return digest.hexdigest()
