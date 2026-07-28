from __future__ import annotations

from datetime import UTC, datetime

from bson import ObjectId
from pymongo.errors import DuplicateKeyError

from app.serializers import serialize_datetime, serialize_object_id


VIDEO_PROCESSING_CONSENT = "video_processing"


def get_video_consent_record(
    db,
    user_id: ObjectId,
    version: str,
) -> dict | None:
    return db.workerConsents.find_one(
        {
            "userId": user_id,
            "type": VIDEO_PROCESSING_CONSENT,
            "version": version,
        }
    )


def get_current_video_consent(
    db,
    user_id: ObjectId,
    version: str,
) -> dict | None:
    consent = get_video_consent_record(db, user_id, version)
    return (
        consent
        if consent is not None and consent.get("revokedAt") is None
        else None
    )


def accept_video_consent(
    db,
    *,
    user_id: ObjectId,
    version: str,
    policy_url: str,
    app_version_code: str | None,
    app_version_name: str | None,
) -> dict:
    query = {
        "userId": user_id,
        "type": VIDEO_PROCESSING_CONSENT,
        "version": version,
    }
    for _ in range(3):
        existing = db.workerConsents.find_one(query)
        if existing and existing.get("revokedAt") is None:
            return existing

        now = datetime.now(UTC)
        version_code = _bounded_header(app_version_code)
        version_name = _bounded_header(app_version_name)
        event = {
            "event": "accepted",
            "occurredAt": now,
            "appVersionCode": version_code,
            "appVersionName": version_name,
        }
        if existing is None:
            document = {
                **query,
                "status": "accepted",
                "policyUrl": policy_url,
                "acceptedAt": now,
                "revokedAt": None,
                "appVersionCode": version_code,
                "appVersionName": version_name,
                "events": [event],
                "createdAt": now,
                "updatedAt": now,
            }
            try:
                result = db.workerConsents.insert_one(document)
            except DuplicateKeyError:
                continue
            document["_id"] = result.inserted_id
            return document

        result = db.workerConsents.update_one(
            {
                "_id": existing["_id"],
                "updatedAt": existing.get("updatedAt"),
            },
            {
                "$set": {
                    "status": "accepted",
                    "policyUrl": policy_url,
                    "acceptedAt": now,
                    "revokedAt": None,
                    "appVersionCode": version_code,
                    "appVersionName": version_name,
                    "events": [
                        *_consent_events(existing),
                        event,
                    ],
                    "updatedAt": now,
                }
            },
        )
        if result.modified_count == 1:
            return db.workerConsents.find_one(
                {"_id": existing["_id"]}
            )
    raise RuntimeError("Consent changed concurrently")


def revoke_video_consent(
    db,
    *,
    user_id: ObjectId,
    version: str,
) -> dict | None:
    query = {
        "userId": user_id,
        "type": VIDEO_PROCESSING_CONSENT,
        "version": version,
    }
    for _ in range(3):
        existing = db.workerConsents.find_one(query)
        if existing is None or existing.get("revokedAt") is not None:
            return existing
        now = datetime.now(UTC)
        result = db.workerConsents.update_one(
            {
                "_id": existing["_id"],
                "updatedAt": existing.get("updatedAt"),
                "revokedAt": None,
            },
            {
                "$set": {
                    "status": "revoked",
                    "revokedAt": now,
                    "events": [
                        *_consent_events(existing),
                        {
                            "event": "revoked",
                            "occurredAt": now,
                        },
                    ],
                    "updatedAt": now,
                }
            },
        )
        if result.modified_count == 1:
            return db.workerConsents.find_one(
                {"_id": existing["_id"]}
            )
    raise RuntimeError("Consent changed concurrently")


def serialize_worker_consent(
    consent: dict | None,
    *,
    version: str,
    policy_url: str,
) -> dict:
    if consent is None:
        return {
            "id": None,
            "type": VIDEO_PROCESSING_CONSENT,
            "version": version,
            "status": "required",
            "policyUrl": policy_url,
            "acceptedAt": None,
            "revokedAt": None,
            "appVersionCode": None,
            "appVersionName": None,
            "events": [],
        }
    return {
        "id": serialize_object_id(consent.get("_id")),
        "type": consent.get("type", VIDEO_PROCESSING_CONSENT),
        "version": consent.get("version", version),
        "status": (
            "revoked"
            if consent.get("revokedAt")
            else consent.get("status", "accepted")
        ),
        "policyUrl": consent.get("policyUrl", policy_url),
        "acceptedAt": serialize_datetime(consent.get("acceptedAt")),
        "revokedAt": serialize_datetime(consent.get("revokedAt")),
        "appVersionCode": consent.get("appVersionCode"),
        "appVersionName": consent.get("appVersionName"),
        "events": [
            {
                "event": item.get("event"),
                "occurredAt": serialize_datetime(
                    item.get("occurredAt")
                ),
                "appVersionCode": item.get("appVersionCode"),
                "appVersionName": item.get("appVersionName"),
            }
            for item in _consent_events(consent)
        ],
    }


def _bounded_header(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized[:100] or None


def _consent_events(consent: dict) -> list[dict]:
    events = [
        item
        for item in consent.get("events", [])
        if (
            isinstance(item, dict)
            and item.get("event") in {"accepted", "revoked"}
            and isinstance(item.get("occurredAt"), datetime)
        )
    ]
    if events:
        return events

    legacy_events = []
    if isinstance(consent.get("acceptedAt"), datetime):
        legacy_events.append(
            {
                "event": "accepted",
                "occurredAt": consent["acceptedAt"],
                "appVersionCode": consent.get("appVersionCode"),
                "appVersionName": consent.get("appVersionName"),
            }
        )
    if isinstance(consent.get("revokedAt"), datetime):
        legacy_events.append(
            {
                "event": "revoked",
                "occurredAt": consent["revokedAt"],
            }
        )
    return sorted(
        legacy_events,
        key=lambda item: item["occurredAt"],
    )
