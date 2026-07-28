from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from werkzeug.exceptions import TooManyRequests


def consume_action_rate_limit(
    db,
    *,
    scope: str,
    subject: str,
    maximum: int,
    window_seconds: int,
    message: str,
) -> None:
    now = datetime.now(UTC)
    window_epoch = (
        int(now.timestamp()) // window_seconds
    ) * window_seconds
    window_start = datetime.fromtimestamp(window_epoch, UTC)
    window_end = window_start + timedelta(seconds=window_seconds)
    query = {
        "rateKey": hashlib.sha256(
            f"{scope}:{subject}".encode("utf-8")
        ).hexdigest(),
        "windowStart": window_start,
    }
    update = {
        "$inc": {"count": 1},
        "$setOnInsert": {
            "scope": scope,
            "createdAt": now,
            "expiresAt": window_end + timedelta(seconds=window_seconds),
        },
    }
    try:
        bucket = db.actionRateLimits.find_one_and_update(
            query,
            update,
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
    except DuplicateKeyError:
        bucket = db.actionRateLimits.find_one_and_update(
            query,
            {"$inc": {"count": 1}},
            return_document=ReturnDocument.AFTER,
        )

    if bucket and bucket.get("count", 0) > maximum:
        error = TooManyRequests(message)
        error.retry_after = max(
            1,
            int((window_end - now).total_seconds()),
        )
        raise error
