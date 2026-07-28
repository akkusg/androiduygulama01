FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UPLOAD_FOLDER=/data/uploads \
    HF_HOME=/home/app/.cache/huggingface

RUN apt-get update \
    && apt-get install --no-install-recommends -y curl ffmpeg libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

COPY . .

RUN groupadd --system app \
    && useradd --system --gid app --create-home app \
    && mkdir -p /data/uploads /home/app/.cache/huggingface \
    && chown -R app:app /app /data/uploads /home/app

USER app

EXPOSE 5050

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl --fail --silent http://127.0.0.1:5050/api/ready > /dev/null || exit 1

CMD ["gunicorn", "--workers", "3", "--bind", "0.0.0.0:5050", "--timeout", "900", "--graceful-timeout", "30", "--keep-alive", "5", "--max-requests", "1000", "--max-requests-jitter", "100", "--access-logfile", "-", "--access-logformat", "%(h)s %(t)s \"%(r)s\" %(s)s %(b)s %(L)s request_id=\"%({x-request-id}o)s\"", "run:app"]
