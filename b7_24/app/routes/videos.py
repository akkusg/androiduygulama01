import hashlib
from datetime import UTC, datetime
from pathlib import Path
# ffprobe runs without a shell and receives a server-generated file path.
import subprocess  # nosec B404
from uuid import uuid4

from bson import ObjectId
from flask import Blueprint, current_app, jsonify, request
from werkzeug.exceptions import (
    BadRequest,
    NotFound,
    PreconditionRequired,
    ServiceUnavailable,
)
from werkzeug.utils import secure_filename

from app.auth import require_worker
from app.db import get_db
from app.serializers import serialize_video
from app.services.consents import get_current_video_consent
from app.services.idempotency import idempotent_worker_upload
from app.services.rate_limit import consume_action_rate_limit
from app.services.video_processing import (
    create_processing_job,
    enqueue_video_processing,
)


videos_bp = Blueprint("videos", __name__)


@videos_bp.post("/api/users/<user_id>/videos")
@require_worker
@idempotent_worker_upload
def upload_video(user_id: str):
    if not ObjectId.is_valid(user_id):
        raise BadRequest("Invalid user id")

    db = get_db()
    user_object_id = ObjectId(user_id)
    if db.users.find_one({"_id": user_object_id}) is None:
        raise NotFound("User not found")
    consent = None
    if current_app.config.get("REQUIRE_VIDEO_CONSENT", True):
        consent = get_current_video_consent(
            db,
            user_object_id,
            current_app.config["VIDEO_CONSENT_VERSION"],
        )
        if consent is None:
            raise PreconditionRequired(
                "Current video processing consent is required"
            )

    file = request.files.get("video")
    if file is None or not file.filename:
        raise BadRequest("multipart form-data field 'video' is required")

    filename = secure_filename(file.filename)
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension not in current_app.config["ALLOWED_VIDEO_EXTENSIONS"]:
        raise BadRequest("Unsupported video type")
    consume_action_rate_limit(
        db,
        scope="video-upload",
        subject=user_id,
        maximum=current_app.config.get(
            "VIDEO_UPLOAD_MAX_REQUESTS", 3
        ),
        window_seconds=current_app.config.get(
            "VIDEO_UPLOAD_RATE_LIMIT_WINDOW_SECONDS", 86400
        ),
        message="Video upload limit reached",
    )

    now = datetime.now(UTC)
    video_id = ObjectId()
    stored_name = f"{video_id}_{uuid4().hex}.{extension}"
    target_dir = Path(current_app.config["UPLOAD_FOLDER"]) / user_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / stored_name
    file.save(target_path)
    try:
        _validate_upload_digest(
            target_path,
            request.headers.get("X-Upload-SHA256"),
        )
        _validate_video_content(target_path)
    except Exception:
        target_path.unlink(missing_ok=True)
        raise

    video = {
        "_id": video_id,
        "userId": user_object_id,
        "originalFilename": filename,
        "storedPath": str(target_path),
        "contentType": file.mimetype,
        "deleteSourceAfterProcessing": current_app.config.get(
            "VIDEO_DELETE_SOURCE_AFTER_PROCESSING", True
        ),
        "status": "processing",
        "createdAt": now,
        "updatedAt": now,
    }
    if consent:
        video.update(
            {
                "consentId": consent["_id"],
                "consentVersion": consent["version"],
                "consentAcceptedAt": consent["acceptedAt"],
            }
        )
    try:
        db.videos.insert_one(video)
        create_processing_job(
            db,
            video,
            current_app.config.get("VIDEO_JOB_MAX_ATTEMPTS", 3),
        )
        db.users.update_one(
            {"_id": user_object_id},
            {
                "$set": {
                    "profileStatus": "video_processing",
                    "videoStatus": "processing",
                    "latestVideoId": video_id,
                    "updatedAt": now,
                }
            },
        )
    except Exception:
        db.videoProcessingJobs.delete_many({"videoId": video_id})
        db.videos.delete_one({"_id": video_id})
        target_path.unlink(missing_ok=True)
        raise

    enqueue_video_processing(current_app._get_current_object(), video_id)

    stored_video = db.videos.find_one({"_id": video_id}) or video
    return jsonify({"video": serialize_video(stored_video)}), 201


def _validate_upload_digest(
    path: Path,
    expected_digest: str | None,
) -> None:
    if not expected_digest:
        return

    digest = hashlib.sha256()
    with path.open("rb") as video_file:
        for chunk in iter(lambda: video_file.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected_digest.lower():
        raise BadRequest(
            "Uploaded video checksum does not match X-Upload-SHA256"
        )


def _validate_video_content(path: Path) -> None:
    if not current_app.config.get("VIDEO_VALIDATE_CONTENT", True):
        return
    if not path.is_file() or path.stat().st_size == 0:
        raise BadRequest("Uploaded video is empty")

    try:
        result = subprocess.run(  # nosec B603
            [
                current_app.config.get("FFPROBE_PATH", "ffprobe"),
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_type",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            check=False,
            text=True,
            timeout=15,
        )
    except FileNotFoundError as error:
        raise ServiceUnavailable(
            "Video validation service is not installed"
        ) from error
    except subprocess.TimeoutExpired as error:
        raise BadRequest("Uploaded video could not be validated") from error

    if result.returncode != 0 or "video" not in result.stdout.splitlines():
        raise BadRequest("Uploaded file does not contain a valid video stream")
