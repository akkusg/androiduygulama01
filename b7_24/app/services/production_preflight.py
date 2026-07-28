from __future__ import annotations

import os
import tempfile
from pathlib import Path

from app.db import ensure_indexes, get_client, get_db
from app.services.auth import VALID_STORED_PHONE
from app.services.push_notifications import (
    prepare_push_worker_runtime,
)
from app.services.runtime_dependencies import executable_available
from app.services.video_processing import (
    prepare_video_worker_runtime,
)


def run_production_preflight(app) -> dict:
    if app.config.get("APP_ENV") != "production":
        raise RuntimeError(
            "Production preflight requires APP_ENV=production"
        )

    with app.app_context():
        get_client().admin.command("ping")
        ensure_indexes()

        invalid_phone_users = get_db().users.count_documents(
            {"phone": {"$not": VALID_STORED_PHONE}}
        )
        if (
            app.config.get("STRICT_DATA_HYGIENE")
            and invalid_phone_users > 0
        ):
            raise RuntimeError(
                "Production preflight found "
                f"{invalid_phone_users} invalid user phone record(s)"
            )

        ffprobe_path = app.config.get("FFPROBE_PATH")
        if (
            app.config.get("VIDEO_VALIDATE_CONTENT", True)
            and not executable_available(ffprobe_path)
        ):
            raise RuntimeError(
                "Production preflight could not execute FFPROBE_PATH"
            )

        _verify_upload_folder(app.config["UPLOAD_FOLDER"])
        video_runtime = prepare_video_worker_runtime(app.config)
        push_runtime = prepare_push_worker_runtime(app.config)

    return {
        "status": "ok",
        "checks": {
            "configuration": "ok",
            "mongo": "ok",
            "indexes": "ok",
            "dataHygiene": {
                "status": "ok",
                "invalidPhoneUsers": invalid_phone_users,
            },
            "uploadFolder": "writable",
            "ffprobe": "ok",
        },
        "workers": {
            "video": video_runtime,
            "push": push_runtime,
        },
    }


def _verify_upload_folder(upload_folder: str) -> None:
    upload_path = Path(upload_folder)
    upload_path.mkdir(parents=True, exist_ok=True)
    temporary_path: str | None = None
    try:
        descriptor, temporary_path = tempfile.mkstemp(
            prefix=".production-preflight-",
            dir=upload_path,
        )
        os.close(descriptor)
    finally:
        if temporary_path:
            Path(temporary_path).unlink(missing_ok=True)
