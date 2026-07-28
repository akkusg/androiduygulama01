from __future__ import annotations

from datetime import UTC, datetime, timedelta

from flask import current_app, g, request

from app.db import get_db


AUDITED_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
TARGET_ARGUMENTS = {
    "application_id",
    "assessment_id",
    "employer_key",
    "invitation_id",
    "item_id",
    "job_id",
    "posting_id",
    "question_id",
    "request_id",
    "resource",
    "route_id",
    "training_id",
    "user_id",
    "worker_id",
}


def record_admin_audit_event(status_code: int) -> None:
    if request.method not in AUDITED_METHODS:
        return

    principal = getattr(g, "auth_session", None)
    if not principal or principal.get("role") != "employer":
        return

    now = datetime.now(UTC)
    view_args = request.view_args or {}
    target = {
        key: str(value)[:128]
        for key, value in view_args.items()
        if key in TARGET_ARGUMENTS and value is not None
    }
    event = {
        "employerKey": principal.get("employerKey"),
        "username": principal.get("username"),
        "method": request.method,
        "action": request.endpoint or "unknown",
        "target": target,
        "statusCode": status_code,
        "outcome": "success" if status_code < 400 else "rejected",
        "authSource": getattr(g, "auth_source", None),
        "requestId": getattr(g, "request_id", None),
        "createdAt": now,
        "purgeAt": now
        + timedelta(
            days=current_app.config["ADMIN_AUDIT_RETENTION_DAYS"]
        ),
    }
    get_db().adminAuditEvents.insert_one(event)
