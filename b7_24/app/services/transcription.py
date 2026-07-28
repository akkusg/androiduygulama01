from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from threading import Lock

from flask import current_app


_MODEL_CACHE = {}
_MODEL_LOCK = Lock()


def warm_up_transcription_provider() -> None:
    provider = current_app.config.get(
        "TRANSCRIPTION_PROVIDER",
        "faster_whisper",
    )
    if provider == "faster_whisper":
        _get_faster_whisper_model()


def transcribe_video(video: dict) -> dict:
    provider = current_app.config.get("TRANSCRIPTION_PROVIDER", "faster_whisper")
    video_path = Path(video["storedPath"])
    started_at = datetime.now(UTC)

    if provider == "static":
        text = current_app.config.get("TRANSCRIPTION_STATIC_TEXT", "")
        return _result(
            provider=provider,
            status="completed" if text else "unavailable",
            text=text,
            segments=[],
            started_at=started_at,
            warnings=[] if text else ["Static transcription text is empty."],
        )

    if provider != "faster_whisper":
        return _result(
            provider=provider,
            status="unavailable",
            text="",
            segments=[],
            started_at=started_at,
            warnings=[f"Unsupported transcription provider: {provider}"],
        )

    try:
        model = _get_faster_whisper_model()
        segments_iter, info = model.transcribe(
            str(video_path),
            language=current_app.config.get("TRANSCRIPTION_LANGUAGE"),
            vad_filter=True,
        )
        segments = [
            {
                "start": float(segment.start),
                "end": float(segment.end),
                "text": segment.text.strip(),
            }
            for segment in segments_iter
            if segment.text.strip()
        ]
        text = " ".join(segment["text"] for segment in segments).strip()
        warnings = []
        if not text:
            warnings.append("No speech was detected in the uploaded video.")

        return _result(
            provider=provider,
            status="completed" if text else "empty",
            text=text,
            segments=segments,
            started_at=started_at,
            language=getattr(info, "language", None),
            languageProbability=getattr(info, "language_probability", None),
            duration=getattr(info, "duration", None),
            warnings=warnings,
        )
    except Exception as error:
        current_app.logger.exception("Transcription failed for video %s", video.get("_id"))
        raise RuntimeError("Video transcription provider failed") from error


def _get_faster_whisper_model():
    from faster_whisper import WhisperModel

    model_size = current_app.config.get("FASTER_WHISPER_MODEL_SIZE", "tiny")
    device = current_app.config.get("FASTER_WHISPER_DEVICE", "cpu")
    compute_type = current_app.config.get("FASTER_WHISPER_COMPUTE_TYPE", "int8")
    cache_key = (model_size, device, compute_type)

    with _MODEL_LOCK:
        if cache_key not in _MODEL_CACHE:
            _MODEL_CACHE[cache_key] = WhisperModel(
                model_size,
                device=device,
                compute_type=compute_type,
            )
        return _MODEL_CACHE[cache_key]


def _result(
    provider: str,
    status: str,
    text: str,
    segments: list[dict],
    started_at: datetime,
    warnings: list[str],
    **metadata,
) -> dict:
    completed_at = datetime.now(UTC)
    return {
        "provider": provider,
        "status": status,
        "text": text,
        "segments": segments,
        "metadata": metadata,
        "warnings": warnings,
        "startedAt": started_at,
        "completedAt": completed_at,
        "createdAt": completed_at,
        "updatedAt": completed_at,
    }
