# b7_24 Backend

Flask + MongoDB backend for the `m7_24` Android application.

## Features

- `GET /api/live` process liveness check
- `GET /api/ready` MongoDB readiness check
- `GET /api/health` service-wide MongoDB, queue, and worker health check
- `GET /api/mobile-config` public Android version and maintenance policy
- Phone-only worker registration after OTP verification
- Phone OTP authentication with revocable Bearer sessions
- Employer authentication and tenant-scoped management APIs
- Browser management panel at `GET /admin`
- Phone-only worker invitations that bind verified workers to the correct employer
- Tenant-scoped worker details with profile, progress, transport, questions, and applications
- `GET /api/users/<user_id>` user detail
- `GET /api/users?phone=<phone>` user lookup by phone
- `POST /api/users/<user_id>/videos` multipart video upload
- Versioned worker consent API required before video/transcript processing
- `DELETE /api/users/<user_id>` authenticated account deletion
- `GET /api/users/<user_id>/data-export` worker JSON data export
- Background video processing job after upload
- Durable MongoDB video queue with leases, retry/backoff, stale-job recovery, terminal-job TTL retention, and worker heartbeats
- Production worker model warm-up before the first healthy heartbeat
- FCM data notifications targeted by Firebase Installation ID (FID)
- Durable per-device push queue with deduplication, retry/backoff, stale-registration cleanup, and worker heartbeats
- Production FCM credential token validation before the first push worker heartbeat
- Automatic raw Video CV deletion after successful processing, with audited retries
- Local speech-to-text with `faster-whisper`
- Skill extraction from the generated transcript
- Candidate profile generation in MongoDB
- Worker confirmation or correction of the video-inferred name without later video processing overwriting the reviewed value
- Job recommendation generation in MongoDB
- `GET /api/users/<user_id>/dashboard` mobile dashboard summary with profile and recommendations
- Worker job applications and employer-side application status updates
- Capacity-backed job offers with worker acceptance or reasoned decline
- Employer job posting CRUD with draft, published, and closed states
- Published posting based profile matching with duplicate-application protection
- Employer-configurable worker hub with assessments, trainings, useful info, shuttle planning, and Q&A
- Worker-specific assessment and training assignments with employer catalog defaults
- Employer question inbox for unanswered worker questions and human responses
- Item-level employer management APIs for worker assessments, trainings, useful info, Q&A knowledge, and shuttle routes
- Worker actions for completing assessments/trainings and requesting shuttle routes with employer approval
- Paginated employer views for workers, postings, applications, and shuttle requests
- Tenant-scoped video processing operations view with audited manual retry for failed current videos
- Worker-scoped device registration and revocation APIs

## Setup

```bash
cd b7_24
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

`requirements.in` and `requirements-dev.in` contain the direct dependencies.
The corresponding `.txt` files are Python 3.13 lock files used by local and
container builds. Regenerate them after an intentional dependency update:

```bash
uv pip compile requirements.in --python-version 3.13 \
  --output-file requirements.txt
uv pip compile requirements-dev.in --python-version 3.13 \
  --output-file requirements-dev.txt
```

Start MongoDB locally:

```bash
docker run --name yedi-yirmi-dort-mongo -p 27017:27017 -d mongo:7
```

Start the API for local development:

```bash
python run.py
```

The API listens on `http://127.0.0.1:5050` by default.

Video uploads are processed asynchronously by default. For deterministic local testing, set:

```bash
VIDEO_PROCESSING_INLINE=1
```

For normal development or production-like operation, keep
`VIDEO_PROCESSING_INLINE=0`, set `VIDEO_PROCESSING_MODE=worker`, and run the API
and worker as separate processes:

```bash
gunicorn --workers 3 --bind 0.0.0.0:5050 \
  --timeout 900 --graceful-timeout 30 \
  --max-requests 1000 --max-requests-jitter 100 \
  --access-logfile - run:app
```

```bash
python worker.py
```

Local development defaults to `PUSH_PROVIDER=disabled`. To exercise queue
delivery without Firebase network calls, use `PUSH_PROVIDER=static` in a test
configuration. Production uses a separate push process:

```bash
python push_worker.py
```

The worker atomically claims queued jobs, renews its lease during transcription,
retries transient failures with exponential backoff, and recovers jobs left by
terminated workers. `GET /api/live` only checks the API process,
`GET /api/ready` verifies MongoDB connectivity, and `GET /api/health` reports
queue counts plus active and startup-validated workers. When worker mode is
enabled and no heartbeat proves the configured model warm-up, the service-wide
health endpoint returns `503` with
`status: degraded`. Container readiness uses `/api/ready`, so a worker outage
does not incorrectly restart a healthy API process.
Terminally failed video jobs also degrade service health. Completed and failed
queue documents receive `purgeAt` and are removed by MongoDB TTL after
`VIDEO_JOB_RETENTION_SECONDS`; index initialization backfills this field on
legacy terminal jobs.
The same payload contains `pushNotifications` provider, active/validated worker,
and queue counts. With `PUSH_PROVIDER=fcm`, a missing worker, a heartbeat
without validated credentials for the configured project, or a terminal
delivery failure makes service health degraded without changing API readiness.
The health payload also reports active and stale idempotency requests; an
expired processing claim marks service health as degraded until it is replayed
or removed by MongoDB TTL cleanup.
Index initialization safely normalizes legacy user phone values when they map
to an unused canonical number. `dataHygiene.invalidPhoneUsers` reports records
that still need manual correction without making the API unavailable.

`VIDEO_DELETE_SOURCE_AFTER_PROCESSING=1` applies data minimization to newly
uploaded videos. After transcription and profile generation complete, the raw
file is removed from the upload volume and the video document records
`sourceDeletionStatus` plus `sourceDeletedAt`. Deletion failures do not undo a
completed profile; the worker retries them every minute and `/api/health`
reports unresolved failures as degraded. Existing records created before this
policy flag are not deleted implicitly.

Every response includes `X-Request-ID`. A valid incoming `X-Request-ID` is
propagated; otherwise the API generates one and includes it in error payloads.
JSON endpoints default to a separate 1 MB body limit while video uploads retain
their configured upload limit.

OTP delivery has atomic MongoDB-backed limits per phone and client IP in
addition to the short per-phone cooldown. `429` responses include
`Retry-After`. When the API is behind a trusted reverse proxy, set
`TRUSTED_PROXY_COUNT` to the exact number of proxies so IP limits use the
validated forwarded client address. Keep it at `0` for direct access.

Authenticated workers also have atomic MongoDB-backed limits for expensive or
operationally sensitive actions. The defaults allow three video uploads per
24 hours and twenty questions per hour. Configure these with
`VIDEO_UPLOAD_RATE_LIMIT_WINDOW_SECONDS`, `VIDEO_UPLOAD_MAX_REQUESTS`,
`WORKER_QUESTION_RATE_LIMIT_WINDOW_SECONDS`, and
`WORKER_QUESTION_MAX_REQUESTS`. Limit buckets expire automatically and `429`
responses include `Retry-After`.

Speech-to-text uses `faster-whisper` by default:

```bash
TRANSCRIPTION_PROVIDER=faster_whisper
TRANSCRIPTION_LANGUAGE=tr
FASTER_WHISPER_MODEL_SIZE=tiny
```

The first real transcription downloads the configured Whisper model from Hugging Face. Tests use the `static` provider so they do not download a model.

## Android emulator URL

Android emulators reach the host machine at `10.0.2.2`, so the app should call:

```text
http://10.0.2.2:5050/api
```

Use the machine LAN IP instead when testing on a physical phone.

For local Android/emulator testing without a real SMS provider, start with a
fixed development code:

```bash
OTP_STATIC_CODE=123456 OTP_EXPOSE_CODE=1 SMS_PROVIDER=static \
ADMIN_USERNAME=admin ADMIN_PASSWORD=local-admin-password \
python run.py
```

Request and verify a phone code:

```bash
curl -X POST http://127.0.0.1:5050/api/auth/otp/request \
  -H "Content-Type: application/json" \
  -d '{"phone":"+905551112233"}'
```

```bash
curl -X POST http://127.0.0.1:5050/api/auth/otp/verify \
  -H "Content-Type: application/json" \
  -d '{"challengeId":"<challenge_id>","phone":"+905551112233","code":"123456"}'
```

Accepted OTP challenges include `resendAfterSeconds`, sourced from
`OTP_REQUEST_COOLDOWN_SECONDS`. Clients should keep resend disabled for that
period. An early resend returns `429` with `Retry-After`.

Authenticated worker requests must include the returned token:

```bash
curl -X PUT http://127.0.0.1:5050/api/users/<user_id>/consents/video-processing \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"version":"video-processing-v1","accepted":true}'
```

The current version and policy URL come from `GET /api/mobile-config`.
Production requires `REQUIRE_VIDEO_CONSENT=1`, a non-empty
`VIDEO_CONSENT_VERSION`, and an absolute HTTPS `PRIVACY_POLICY_URL`. Workers can
read the current record with `GET` or withdraw it with `DELETE` on the same
consent endpoint. Withdrawal blocks future video uploads; it does not silently
delete an already generated profile. Repeated accept/withdraw cycles retain an
ordered event history instead of overwriting the earlier audit timestamps.

```bash
curl -X POST http://127.0.0.1:5050/api/users/<user_id>/videos \
  -H "Authorization: Bearer <access_token>" \
  -H "Idempotency-Key: <unique-key>" \
  -H "X-Upload-SHA256: $(shasum -a 256 /path/to/video.mp4 | cut -d' ' -f1)" \
  -F "video=@/path/to/video.mp4"
```

Registration and OTP verification collect only the phone number. After video
processing has generated a candidate profile, the worker must confirm or
correct the inferred name:

```bash
curl -X PUT http://127.0.0.1:5050/api/users/<user_id>/profile-review \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"name":"Mehmet Yılmaz"}'
```

The endpoint is owner-scoped and rejects review attempts until the latest
video profile is ready. Confirmed and corrected names are propagated to
existing application snapshots and remain authoritative when later videos are
processed.

Workers can permanently close their account with
`DELETE /api/users/<user_id>`. The endpoint removes worker profile, video,
transcript, support assignments, OTP, invitation, session, and recommendation data. Job
applications are retained only as anonymized operational records: candidate
identity, phone, cover note, skills, summary, and free-text history notes are
removed. Raw video cleanup failures are retried by the worker and reported by
`/api/health`.

`GET /api/users/<user_id>/data-export` returns a versioned JSON package with
the authenticated worker's public user, video, transcript, profile,
recommendation, application, question, assessment, training, and shuttle
records plus consent history and non-sensitive device metadata. Firebase
Installation IDs, internal
file paths, auth/OTP hashes, idempotency records, and worker locks are never
included. The response uses an attachment filename and `Cache-Control:
no-store`.

```bash
curl -X POST http://127.0.0.1:5050/api/users/<user_id>/assessments/safety-readiness/complete \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: <unique-key>" \
  -d '{"answers":[{"questionId":"ppe-check","optionId":"ppe-complete"},{"questionId":"unsafe-condition","optionId":"notify-supervisor"}]}'
```

Failed assessments can be submitted again. The result keeps the latest score
along with `attemptCount` and the last 20 entries in `attemptHistory`.

```bash
curl -X POST http://127.0.0.1:5050/api/users/<user_id>/trainings/isg-101/complete \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: <unique-key>" \
  -d '{"completedModules":["ppe","emergency"]}'
```

Training completion requires every configured module exactly once. Progress is
calculated by the server; client-provided percentage values are ignored.
Partial progress can be saved before the training is complete:

```bash
curl -X PUT http://127.0.0.1:5050/api/users/<user_id>/trainings/isg-101/progress \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: <unique-key>" \
  -d '{"completedModules":["ppe"]}'
```

```bash
curl -X POST http://127.0.0.1:5050/api/users/<user_id>/shuttle-requests \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: <unique-key>" \
  -d '{"routeId":"route-1","pickupNote":"Ana duraktan bineceğim"}'
```

Workers can cancel an active requested or confirmed shuttle:

```bash
curl -X POST http://127.0.0.1:5050/api/users/<user_id>/shuttle-requests/<request_id>/cancel \
  -H "Idempotency-Key: <unique-key>"
```

```bash
curl -X POST http://127.0.0.1:5050/api/users/<user_id>/job-applications \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: <unique-key>" \
  -d '{"jobRecommendationId":"<recommendation_id>","coverNote":"Hemen başlayabilirim."}'
```

`GET /api/users/<user_id>/job-applications` returns the worker's application
history even when the original recommendation or posting is no longer active.
Workers can withdraw an application while it is submitted, under review, or
shortlisted:

```bash
curl -X POST http://127.0.0.1:5050/api/users/<user_id>/job-applications/<application_id>/withdraw \
  -H "Authorization: Bearer <access_token>" \
  -H "Idempotency-Key: <unique-key>"
```

Workers can confirm a future active interview or report that they cannot
attend. A decline requires a note so the employer can reschedule:

```bash
curl -X POST http://127.0.0.1:5050/api/users/<user_id>/job-applications/<application_id>/interview-response \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: <unique-key>" \
  -d '{"status":"declined","note":"Bu saatte vardiyadayım, yeniden planlayabilir miyiz?"}'
```

The response is scoped to the current interview plan. Rescheduling replaces
the plan and clears the previous worker response.

Employers can move an application to `offered` with a future start date and
an earlier response deadline. Posting-backed offers reserve one atomic hiring
slot until the offer is accepted, declined, withdrawn by the employer, or
expires. Workers respond with the same idempotency guarantees:

```bash
curl -X POST http://127.0.0.1:5050/api/users/<user_id>/job-applications/<application_id>/offer-response \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: <unique-key>" \
  -d '{"status":"accepted"}'
```

Accepted offers move to `hired`. Declined offers move to `offer_declined` and
require a note; their reserved hiring slot is released immediately.

Video upload, worker question, assessment, training, shuttle, and
job-application mutations require a unique `Idempotency-Key`. Video uploads
also require `X-Upload-SHA256`; the server verifies this digest after saving
the file and uses it as the multipart request fingerprint without buffering
the request body in memory. Successful responses are replayed for the same key
and payload without running the side effect again. Reusing a key for a
different payload returns `409`; records expire after
`IDEMPOTENCY_RETENTION_SECONDS`. Upload claims use
`IDEMPOTENCY_UPLOAD_PROCESSING_TIMEOUT_SECONDS` because they include mobile
transfer time.

```bash
curl http://127.0.0.1:5050/api/employers/<employer_key>/job-applications
```

Employer job postings are managed through:

```text
GET    /api/employers/<employer_key>/job-postings
POST   /api/employers/<employer_key>/job-postings
PATCH  /api/employers/<employer_key>/job-postings/<posting_id>
DELETE /api/employers/<employer_key>/job-postings/<posting_id>
```

Only published postings are matched to worker profiles. Production disables
the development fallback catalog, so no sample job is presented as a real
opening. Applications remain
linked to their posting even after a new video creates a new recommendation.
Postings with applications cannot be deleted and must be closed.

Failed video processing jobs can be inspected and retried from the management
panel or through:

```text
GET  /api/employers/<employer_key>/video-processing-jobs?status=failed
POST /api/employers/<employer_key>/video-processing-jobs/<job_id>/retry
```

Manual retry requires the failed job to belong to the employer, reference the
worker's current video, and still have its source file. The action resets the
automatic attempt budget, records the prior error in retry history, and is
included in the admin audit log.

```bash
curl -X PATCH http://127.0.0.1:5050/api/employers/<employer_key>/job-applications/<application_id> \
  -H "Content-Type: application/json" \
  -d '{"status":"shortlisted","note":"Telefon görüşmesine alınacak."}'
```

`reviewing` veya `shortlisted` başvurular için aynı güncellemede yapılandırılmış
görüşme planı da kaydedilebilir. Aynı durumla tekrar gönderildiğinde plan
yeniden zamanlanır; `interview: null` mevcut planı kaldırır.

```bash
curl -X PATCH http://127.0.0.1:5050/api/employers/<employer_key>/job-applications/<application_id> \
  -H "Content-Type: application/json" \
  -d '{"status":"shortlisted","interview":{"scheduledAt":"2026-08-01T07:30:00Z","type":"onsite","location":"Kocaeli Fabrikası","note":"Kimliğinizi getirin."}}'
```

```bash
curl http://127.0.0.1:5050/api/employers/<employer_key>/shuttle-requests
```

```bash
curl -X PATCH http://127.0.0.1:5050/api/employers/<employer_key>/shuttle-requests/<request_id> \
  -H "Content-Type: application/json" \
  -d '{"status":"confirmed","decisionNote":"Servis listesine eklendi."}'
```

Worker config resources can be managed without replacing the full config:

```text
POST   /api/employers/<employer_key>/worker-config/assessments
PATCH  /api/employers/<employer_key>/worker-config/assessments/<assessment_id>
DELETE /api/employers/<employer_key>/worker-config/assessments/<assessment_id>

POST   /api/employers/<employer_key>/worker-config/trainings
PATCH  /api/employers/<employer_key>/worker-config/trainings/<training_id>
DELETE /api/employers/<employer_key>/worker-config/trainings/<training_id>

POST   /api/employers/<employer_key>/worker-config/useful-info
PATCH  /api/employers/<employer_key>/worker-config/useful-info/<info_id>
DELETE /api/employers/<employer_key>/worker-config/useful-info/<info_id>

POST   /api/employers/<employer_key>/worker-config/qa-knowledge
PATCH  /api/employers/<employer_key>/worker-config/qa-knowledge/<knowledge_id>
DELETE /api/employers/<employer_key>/worker-config/qa-knowledge/<knowledge_id>

PATCH  /api/employers/<employer_key>/worker-config/shuttle
POST   /api/employers/<employer_key>/worker-config/shuttle/routes
PATCH  /api/employers/<employer_key>/worker-config/shuttle/routes/<route_id>
DELETE /api/employers/<employer_key>/worker-config/shuttle/routes/<route_id>
```

The original `PUT /api/employers/<employer_key>/worker-config` endpoint remains
available for validated bulk replacement of selected config sections.

## Management panel

Open `http://127.0.0.1:5050/admin` and sign in with the configured
`ADMIN_USERNAME` plus `ADMIN_PASSWORD` or `ADMIN_PASSWORD_HASH`. The panel
manages workers, job postings, job applications, shuttle requests, assessments, trainings,
useful information, Q&A knowledge, and shuttle routes for
`ADMIN_EMPLOYER_KEY`. Employers can pre-invite a worker by phone; after that
phone completes OTP verification in the mobile app, the worker is automatically
assigned to the inviting employer without adding another field to registration.
The worker list opens a consolidated detail view for the inferred candidate
profile, assessment scores, training progress, current shuttle request, recent
questions, job applications, and worker-specific content assignments. Without
an explicit assignment, all published assessment and training content is
available to the worker. Once saved, the mobile dashboard only returns the
selected content; draft and archived items are never assignable. The corresponding
`GET /api/employers/<employer_key>/workers/<worker_id>` endpoint does not expose
workers from another employer.
Assignments can also be read and replaced through
`GET|PUT /api/employers/<employer_key>/workers/<worker_id>/support-assignments`.
The `Veri Kalitesi` view lists tenant-scoped legacy workers whose stored phone
number cannot pass current validation. An employer can correct the phone only
when the legacy number has never been verified and has no auth session. The
corrected number remains unverified until the worker completes SMS OTP login.
A legacy record can be cleaned only when it is also video-free; cleanup
requires typing `TEMIZLE`, removes worker personal/support data, and retains
job applications only after anonymizing candidate identity and free text.
Both operations are CSRF-protected and written to the admin audit log:

```text
GET    /api/employers/<employer_key>/data-hygiene/workers
PATCH  /api/employers/<employer_key>/data-hygiene/workers/<worker_id>/phone
DELETE /api/employers/<employer_key>/data-hygiene/workers/<worker_id>
```

Production operators can inspect all tenants without exposing full phone
numbers and can run the same guarded remediations from the container:

```bash
python data_hygiene.py report
python data_hygiene.py report --employer-key default
python data_hygiene.py correct-phone \
  --employer-key default --worker-id <worker_id> --phone "+90..."
python data_hygiene.py cleanup-worker \
  --employer-key default --worker-id <worker_id> --confirmation TEMIZLE
```

The report is read-only, bounded to 1,000 worker rows, and marks truncation.
Mutation commands require both the tenant and exact worker ID. The cleanup
command applies the same unverified/session-free/video-free guard as the
management panel.

Browser admin sessions use an HttpOnly, `SameSite=Strict` cookie instead of
storing bearer tokens in JavaScript-accessible storage. A separate CSRF cookie
is restored when needed, and every state-changing management request must send
its value in `X-CSRF-Token`. Employer mutations are written to the tenant-scoped
`adminAuditEvents` collection without request bodies, credentials, cookies, or
phone numbers.

Generate a Werkzeug-compatible password hash:

```bash
python -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('replace-me'))"
```

## Production

Production startup rejects unsafe auth configuration. Set `APP_ENV=production`,
use a unique `SECRET_KEY` of at least 32 characters, configure a real SMS
provider, keep `OTP_STATIC_CODE` empty and `OTP_EXPOSE_CODE=0`, and provide
`ADMIN_PASSWORD_HASH` instead of `ADMIN_PASSWORD`. The hash must be a valid
Werkzeug scrypt hash using at least the current default work parameters; the
generation command in the management panel section produces this format. The current production SMS
provider is Twilio; all three `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, and
`TWILIO_FROM_NUMBER` values are required. Production also requires
`TRANSCRIPTION_PROVIDER=faster_whisper` and
`VIDEO_DELETE_SOURCE_AFTER_PROCESSING=1`.
Set `FFPROBE_PATH` to the absolute ffprobe executable path; the container uses
`/usr/bin/ffprobe`.
`VIDEO_JOB_RETENTION_SECONDS` controls terminal queue audit retention and must
be between 1 and 30 days.
Production requires `VIDEO_WORKER_WARMUP_MODEL=1`. The video worker loads the
configured faster-whisper model before publishing its first healthy heartbeat,
so a missing model or unavailable model cache prevents a false-ready worker.
`VIDEO_WORKER_HEALTH_START_PERIOD` defaults to five minutes in Compose to allow
the initial model cache download and load before healthcheck failures count.
The video worker receives a 20-minute Compose stop grace period so deployments
can finish an active transcription and release its lease cleanly. The push
worker receives two minutes for its shorter network jobs.
Set `TRUSTED_HOSTS` to the public API hostname (comma-separated when needed).
Production rejects the default localhost Mongo URI; use an authenticated
external MongoDB connection string with transport encryption enabled.
Production also requires `STRICT_DATA_HYGIENE=1`; any user record whose phone
cannot be normalized makes `/api/health` return `503` until migrated or
removed.
`ADMIN_AUDIT_RETENTION_DAYS` controls automatic audit TTL cleanup and must be
between 30 and 3650 days.
`ACCOUNT_DELETION_AUDIT_RETENTION_DAYS` controls TTL cleanup for completed
account deletion audit records and must be between 30 and 3650 days. Pending or
failed file cleanup records are retained until the cleanup is resolved.
Production also requires
`MOBILE_MIN_SUPPORTED_VERSION_CODE <= MOBILE_LATEST_VERSION_CODE` and an
absolute HTTPS `MOBILE_UPDATE_URL`. Set `MOBILE_MAINTENANCE_MODE=1` to block
mobile entry with `MOBILE_MAINTENANCE_MESSAGE`; raise the minimum supported
version to require an Android update.
Set a real absolute HTTPS `PRIVACY_POLICY_URL`, keep
`REQUIRE_VIDEO_CONSENT=1`, and change `VIDEO_CONSENT_VERSION` whenever the
published processing terms materially change. Placeholder policy hosts are
rejected at startup.
Set `PUSH_PROVIDER=fcm` and `FCM_PROJECT_ID` to the Firebase project used by
the Android app. The push worker reads Application Default Credentials from
`GOOGLE_APPLICATION_CREDENTIALS`; use a least-privilege Firebase service
account file and never add it to source control. The worker validates the
credential project and refreshes an OAuth token before publishing its first
heartbeat; production requires `PUSH_WORKER_VALIDATE_CREDENTIALS=1`.
`PUSH_WORKER_HEALTH_START_PERIOD` defaults to 60 seconds in Compose for this
network preflight. FCM registrations
are stored as Firebase Installation IDs, refreshed on mobile startup, and
deactivated after `PUSH_REGISTRATION_RETENTION_DAYS`. Per-worker active and
stored registration caps are controlled by
`PUSH_MAX_ACTIVE_REGISTRATIONS_PER_WORKER` and
`PUSH_MAX_STORED_REGISTRATIONS_PER_WORKER`; inactive records receive a MongoDB
TTL so repeated installations cannot grow the collection without bound.

Serve the API, video queue, and push queue as separate production processes:

```bash
gunicorn --workers 3 --bind 0.0.0.0:5050 \
  --timeout 900 --graceful-timeout 30 \
  --max-requests 1000 --max-requests-jitter 100 \
  --access-logfile - run:app
```

```bash
python worker.py
```

```bash
GOOGLE_APPLICATION_CREDENTIALS=/run/secrets/firebase-service-account.json \
  python push_worker.py
```

Terminate TLS at the load balancer or reverse proxy. Release Android builds
disable cleartext HTTP and therefore require an HTTPS `API_BASE_URL`.

### Containers

`Dockerfile` packages FFmpeg, the Flask API, transcription dependencies, and
both worker runtimes under a non-root user. `compose.yaml` runs the API, video
worker, and push worker separately with a shared persistent upload volume,
read-only root filesystems, dropped Linux capabilities, mandatory production
secrets, an init process, bounded PID usage, rotated container logs, API
readiness checks, and MongoDB-backed worker heartbeat
healthchecks. The Firebase service account is mounted read-only into only the
push worker. `.dockerignore` excludes environment files, private key formats,
Firebase service accounts, local uploads, and test artifacts from the image
build context.

```bash
cp .env.production.example .env.production
docker compose --env-file .env.production run --rm push-worker \
  python production_preflight.py
docker compose --env-file .env.production up --build -d
docker compose ps
```

The preflight command applies MongoDB indexes and safe legacy backfills, checks
strict phone-data hygiene and upload-volume writes, executes `ffprobe`, warms
the configured Whisper model, and refreshes the FCM credential token. It exits
non-zero before deployment when any required dependency is unavailable and
prints only non-secret runtime metadata.

The production compose file expects an external authenticated MongoDB URI and
does not embed database credentials in source control. TLS should still
terminate in front of port `5050`.

## Tests

Tests require a MongoDB instance reachable through `mongodb://localhost:27017`.

```bash
pip install -r requirements-dev.txt
pytest
```
