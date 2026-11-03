# Streaming platform (MVP)

Upload videos, encode them to 480p/720p/1080p HLS, and stream them with adaptive bitrate.
Built phase by phase from the *Video Streaming Platform – MVP Blueprint*.

**Status:**
- **Phase 1 (foundation), done:** Docker stack, Django + JWT auth, React + Redux Saga shell, CI.
- **Phase 2 (upload), done:** direct-to-S3 uploads (single or multipart) with progress and cancel, and a `video.uploaded` event on Kafka.
- **Phase 3 (encoding), done:** an FFmpeg worker encodes HLS 480p/720p/1080p plus a thumbnail, with retries and a DLQ; a status consumer updates the database; the UI polls until a video is ready.
- **Phase 4 (playback), done:** CDN delivery with CloudFront signed cookies, an hls.js player with automatic and manual quality, public browse and watch pages, and Terraform for S3 and CloudFront.
- **Phase 5 (subscribers and events), done:** playback events through Kafka into MongoDB, resume where you left off, in-app notifications, and follows with a Following feed.
- **Phase 6, part A (hardening), done:** JSON logs with correlation IDs, Sentry, a readiness check,
  consumer-lag and DLQ monitoring, CSP and security headers, deploy checks and image scanning in CI.
- **Phase 6, part B (deployment), written and validated, not yet applied to AWS:** Terraform for the whole
  AWS platform, a production Compose file and deploy scripts, a GitHub Actions pipeline (staging → smoke
  test → approval → production, plus rollback) and an environment-agnostic smoke test.
  See **[docs/runbook.md](docs/runbook.md)**.

- **Phase 7 (tracking and dashboards), done locally:** a daily Airflow pipeline from raw events to analytics
  tables, and three Superset dashboards defined in code. See [Analytics](#analytics).
- **Phase 8 (recommendations), done locally:** trending and popular lists, similar videos and personal picks,
  precomputed nightly. See [Recommendations](#recommendations). Collaborative filtering (step 51) is deferred.
- **Phase 9 (video intelligence), done locally:** an optional ML worker writes Whisper subtitles and CLIP tags,
  moderation flags and a better thumbnail, and search covers titles, tags and speech.
  See [Video intelligence](#video-intelligence).

## Quick start

Requires Docker Desktop. Node and FFmpeg don't need to be installed locally.

```sh
cp .env.example .env          # then set DJANGO_SECRET_KEY to a long random string
docker compose up -d --build
```

Open http://localhost:8080 and register an account.

Create an admin user for http://localhost:8080/admin/:

```sh
docker compose exec django python manage.py createsuperuser
```

## Services

| Service    | Port (host)  | Notes                                                              |
|------------|--------------|--------------------------------------------------------------------|
| nginx      | 8080         | Serves the React build, proxies `/api`, `/admin`, `/static`; rate limits auth |
| django     | (internal)   | Gunicorn; runs migrations on start                                 |
| postgres   | 5432         | Users now; videos and renditions from Phase 2                      |
| kafka      | 29092        | KRaft, single node. Inside Docker use `kafka:9092`                 |
| s3         | 8333         | SeaweedFS S3 API (local stand-in for AWS S3)                       |
| cdn        | (via nginx `/cdn/`) | Local stand-in for CloudFront: checks signed cookies, only reader of the bucket |
| mongo      | 27017        | Playback events, watch progress, notifications, feeds              |
| encoder    | (none)       | FFmpeg worker (group `encoder`), limited to 2 CPUs. `--scale encoder=N` |
| monitor            | (none) | `manage.py monitor`: consumer lag and DLQ size every 60 s           |
| status-consumer    | (none) | `run_consumer status`: video.ready/failed → Video rows (group `api-status`) |
| analytics-consumer | (none) | `run_consumer analytics`: events.playback → MongoDB (group `analytics`) |
| notify-consumer    | (none) | `run_consumer notify`: video.ready/failed → notifications (group `notify`) |
| feed-consumer      | (none) | `run_consumer feed`: video.ready → followers' feeds (group `feed`)  |

## Layout

```
backend/    Django: config/, accounts/, videos/, events/, notifications/, social/, common/ (Kafka, S3, Mongo, logs)
frontend/   React + TypeScript + Vite: app/ (store, sagas, API client), features/ (auth, upload, videos, player, ...)
worker/     FFmpeg encoding worker
infra/      nginx/ (gateway config), local-cdn/ (CloudFront stand-in), terraform/ (bootstrap, app, modules/)
deploy/     production Compose file, host deploy script, CI rollout script, smoke test
docs/       runbook.md: AWS setup, deploys, rollback, operations
data/       pipeline/ (pandas aggregation), airflow/ (DAG), superset/ (dashboards as code)
```

## Auth design

- `POST /api/auth/login/` returns a 15-minute **access token** in the body and sets a 7-day **refresh token**
  as an `httpOnly`, `SameSite=Lax` cookie scoped to `/api/auth/`.
- The React app keeps the access token in Redux memory only. On load it calls `/api/auth/refresh/`
  to restore the session from the cookie.
- On a 401 the axios interceptor refreshes once and retries. Parallel 401s share one refresh request.
- Refresh tokens rotate on every use and the old one is blacklisted. Logout blacklists the current token.
- The Django admin uses normal session auth.

## Upload flow

1. `POST /api/videos/` (title, filename, size, content_type) creates a `Video` (`uploading`) and returns either
   one presigned PUT URL (≤ 100 MB) or presigned URLs for each 16 MB part of an S3 multipart upload.
2. The browser PUTs the bytes **straight to S3**. Django never sees them. Each part's `ETag` is collected
   (the bucket CORS rule exposes it).
3. `POST /api/videos/{id}/complete/` (with `parts` for multipart) assembles the multipart upload, checks the object
   with a HEAD request (it must exist with the declared size), sets status `uploaded` and publishes `video.uploaded`
   keyed by `video_id`. If publishing fails, the status change rolls back and the call can be retried.
   Retrying after success changes nothing.
4. Cancel calls `DELETE /api/videos/{id}/`, which aborts the multipart upload and removes the raw object.

Other endpoints: `GET /api/videos/` returns ready videos (`?mine=true` returns your own in any status) and
`GET /api/videos/{id}/` returns one video.

On startup the django container runs `manage.py ensure_infra`, which creates the bucket (with CORS and lifecycle
rules) and the Kafka topics `video.uploaded`, `video.ready`, `video.failed`, `video.uploaded.dlq` and
`events.playback` (6 partitions each). Read the topic:

```sh
docker compose exec kafka /opt/kafka/bin/kafka-console-consumer.sh --bootstrap-server localhost:9092 \
  --topic video.uploaded --from-beginning --property print.key=true
```

## Encoding pipeline

```
video.uploaded ──> encoder ──> S3 hls/{id}/master.m3u8, {480p,720p,1080p}/index.m3u8 + seg_NNN.ts
                      │        S3 thumbnails/{id}/default.jpg
                      ├──> video.ready  ──> status-consumer ──> Video = ready, Rendition rows
                      └──> video.failed ──> status-consumer ──> Video = failed (+ error_message)
                           video.uploaded.dlq  (original message + error, for inspection)
```

- **Ladder:** only renditions the source can fill. A 720p source gets 480p and 720p. Portrait sources get
  portrait renditions. Sources below 480p get one rendition at their own size. Keyframes every 2 s with
  6 s segments, so all renditions cut at the same points and the player can switch cleanly.
- **Claiming:** the worker's only DB write is `status = processing` together with the message's `event_id`.
  A redelivery of the same message (after a crash) takes the video back over; a duplicate message is skipped.
  `ready` and `failed` are written only by the status consumer.
- **Ordering:** `/complete` commits `uploaded` before publishing, so the encoder never sees an event before
  the row is in the right state.
- **Failures:** up to 3 attempts with backoff (5 s, 15 s). An unusable file (not a video, or over
  `MAX_VIDEO_DURATION_SEC`, 2 h by default) fails at once with a user-facing reason. After that the worker
  publishes `video.failed`, sends the message to the DLQ and commits. Temp files are always removed.
- **Long encodes:** the worker pauses its partitions and keeps polling while FFmpeg runs in a background
  thread, so Kafka never times it out of the consumer group (`max.poll.interval.ms`).
- **Deleting** a video removes its raw upload, HLS output and thumbnail. If it's mid-encode, the worker
  cleans up its own output once it finishes.

Inspect the DLQ:

```sh
docker compose exec kafka /opt/kafka/bin/kafka-console-consumer.sh --bootstrap-server localhost:9092 \
  --topic video.uploaded.dlq --from-beginning
```

## Playback

- **Public pages:** `/` (browse) and `/watch/:id` are public. `/my` and `/upload` need an account.
- **Signed cookies:** `GET /api/videos/{id}/` for a ready video returns `playback.hls_url` and sets three
  CloudFront signed cookies (`CloudFront-Policy`, `-Signature`, `-Key-Pair-Id`).
  - The policy covers `<CDN_BASE_URL>/hls/<id>/*` only, the cookie path matches it, and the cookies are
    `HttpOnly`.
  - They last for the video's duration plus 2 hours (at most 12 hours).
  - Cookies are used instead of signed URLs because one video means hundreds of segment requests.
- **Player:** hls.js chooses the quality from measured bandwidth, and the viewer can pick one by hand.
  Safari and iOS play HLS natively (the browser picks the quality).
  - If the CDN answers 403 (cookies expired), the player re-fetches the video for fresh cookies and
    carries on from the same position.
- **CDN rules** (CloudFront in AWS, `infra/local-cdn` locally; the same rules in both):

  | Path            | Access |
  |-----------------|--------|
  | `/hls/*`        | Signed cookies required. Segments cached for 1 year, playlists for 60 s. |
  | `/thumbnails/*` | Public |
  | anything else   | Denied. The bucket policy lets CloudFront read only `hls/` and `thumbnails/`. |

- **Local signing key:** generated on first start into the `cdn-keys` Docker volume.
- **AWS:** `infra/terraform/media` creates the private bucket (CORS, lifecycle, encryption), Origin Access
  Control, the bucket policy, the public key and key group, the cache and CORS policies, and the
  distribution. Then set `CDN_BASE_URL`, `CLOUDFRONT_KEY_PAIR_ID`, `CLOUDFRONT_PRIVATE_KEY` (from Secrets
  Manager) and `CDN_COOKIE_DOMAIN`.
  - The CDN must run on a subdomain of the app's domain (for example `media.example.com` with
    `CDN_COOKIE_DOMAIN=.example.com`). Otherwise the browser won't send the API's cookies to it.

## Events and subscribers

```
player ─(PlaybackTracker)─> eventsSaga ─> POST /api/events/batch/ ─> events.playback (key: video_id)
                                                                          └─> analytics-consumer ─> MongoDB
video.ready / video.failed ─> notify-consumer ─> notifications (MongoDB) ─> bell (polled every 30 s)
video.ready ───────────────> feed-consumer ───> feed_items (MongoDB, fan-out to followers) ─> /following
```

- **Tracked events:** play, pause, seek (from/to), progress (every 10 s of playback), quality_change
  (from/to, auto or manual), buffering (stall duration) and complete (at 95%, with seconds actually watched).
  Each event carries `session_id`, the user (or an anonymous browser id), the quality, a client timestamp,
  and the device and country added by the server. The country comes from the viewer's IP address and the address
  itself is never stored with the event. It uses [DB-IP's free database](https://db-ip.com) (CC BY 4.0), built into the
  image, so there are no outside calls and it can be wrong for VPNs and some mobile networks. Local requests have no
  country, because private addresses aren't in it. The version is pinned in `backend/Dockerfile`, so update it
  occasionally.
- **Batching:** the saga sends events every 15 s or once 50 are waiting. When the page is hidden or
  closed, it sends the rest with `fetch(..., {keepalive: true})`, which unlike `sendBeacon` can carry the
  `Authorization` header (`sendBeacon` is the fallback). That final batch goes to `?final=1`, so an
  access token that has just expired doesn't lose the events: they're recorded anonymously.
- **Intake:** validates and publishes in one Kafka flush. It never writes a database in the request path.
- **MongoDB:**
  - `playback_events`: one document per `event_id` (so redelivery is harmless), deleted after 90 days
    by a TTL index.
  - `watch_progress`: one row per user and video, which only ever moves forward in time, so late or
    replayed events can't move it back.
  - `notifications` and `feed_items`: one per event and one per (user, video) respectively, so neither
    duplicates on replay.
- **Resume:** for a logged-in viewer, `GET /api/videos/{id}/` returns `resume_position_sec`. It's left
  out if the video was finished or the position is within 5 s of the start or 10 s of the end. The player
  starts there and shows "Resuming from m:ss · Start over".
- **Follows:** `POST|DELETE /api/users/{id}/follow/` and `GET /api/feed/`. Notifications:
  `GET /api/notifications/` and `POST /api/notifications/read/`.

## Analytics

Optional and heavy (Airflow alone uses over 1 GB of memory), so it sits behind a Compose profile:

```sh
docker compose --profile data up -d --build
```

| Tool | URL | Login |
|---|---|---|
| Airflow | http://localhost:8081 | none (local only, bound to 127.0.0.1) |
| Superset | http://localhost:8088 | `admin` / `SUPERSET_ADMIN_PASSWORD` from `.env` |

**Flow:** `playback_events` (MongoDB) → DAG `daily_video_pipeline` (02:00 UTC, pandas) → analytics tables
(PostgreSQL) → Superset dashboards **Platform overview**, **Video retention** and **Streaming quality**.

- **Tables** (Django migrations, `backend/analytics`): `daily_video_stats`, `daily_video_retention`,
  `daily_streaming_quality`, `daily_platform_stats`.
- **Definitions:**
  - A *view* is a session with a play event, and days are by server receive time.
  - Watch time is reconstructed from the event stream (`data/pipeline/sessions.py`), so pauses, seeks and
    rewatches are handled.
  - *Avg % watched* counts each part of the video once per session.
  - A *stall* is a wait after playback has started; waits before it are startup time.
- **Re-runs are safe:** each day is replaced in one transaction, so a re-run can't double-count. A data quality
  task fails the DAG if the tables disagree with each other or with the raw events.
- **Access:** Superset connects as `analytics_ro`, which can read only analytics tables and views, never
  `accounts_user`. The pipeline's `analytics_etl` role writes only its own tables.
- **Dashboards are code:** edit `data/superset/build_assets.py` and restart `superset`. Changes made only in the
  Superset UI to these dashboards are overwritten on the next start.

```sh
# Recompute a range
docker compose --profile data exec airflow python -m pipeline.run --from 2026-10-01 --to 2026-10-31
# Demo data, for local dashboards (session ids start with "demo-"; refuses to run against Atlas)
docker compose --profile data exec airflow python -m pipeline.seed_demo --days 14
docker compose --profile data exec airflow python -m pipeline.seed_demo --clear
```

After `--clear`, recompute the same dates so the tables drop the demo numbers. The data stack isn't part of
the AWS Terraform yet.

## Recommendations

Precomputed by the nightly DAG and stored in PostgreSQL; the API only reads them, so there's no live model serving.
Needs the data stack running to refresh; the API keeps serving the last results without it.

| Endpoint | Returns |
|---|---|
| `GET /api/recommendations/` | Personal picks if there are any, else trending, else newest. `source` says which |
| `GET /api/recommendations/trending/` | Views over 7 days, each day counting 0.7× the next |
| `GET /api/recommendations/popular/` | Most watch time over 30 days |
| `GET /api/videos/{id}/similar/` | Videos with similar text, else trending. `source` says which |

- **Embeddings:** `all-MiniLM-L6-v2` over title + description, run with `fastembed` (ONNX, no PyTorch). Only new
  or edited videos are re-embedded.
- **Personal picks:** the average of what a user watched in the last 90 days, weighted towards what they finished,
  matched against videos they haven't started and didn't upload.
- **Fresh enough:** deleted videos drop out immediately. A new video has no similar list or picks until the next
  nightly run.
- **What gets embedded:** title, description, topic tags, then the start of the transcript, so a video is
  re-embedded the night after the ML worker analyses it. Moderation flags are left out.
- **Known limit:** short titles give the model little to go on. On 24 hand-labelled titles, the cutoff of 0.2 kept
  41% of same-topic pairs and let through 4% of different-topic ones. So some related videos aren't linked (they
  get trending instead), and the occasional wrong match is possible. See `data/pipeline/recommend.py`.
- **Refresh by hand:**

  ```sh
  docker compose --profile data exec airflow python -m pipeline.run --from 2026-11-01 --recommendations
  ```

## Video intelligence

An optional worker that consumes `video.ready`. Videos play with or without it, and search still covers titles and
descriptions. It isn't part of the AWS Terraform yet.

```sh
# In .env, set ML_WORKER_DB_PASSWORD. Once set, the monitor expects the worker to be consuming.
docker compose --profile ml up -d --build
```

On first start it works through every `video.ready` still on Kafka, so existing videos get analysed too.

| Output | Where | Who sees it |
|---|---|---|
| Subtitles (WebVTT) | S3, `hls/{id}/subtitles/{language}.vtt`, behind the same signed cookies as the video | Viewers, off by default |
| Transcript | `video_transcripts` | Search, with the spoken match highlighted |
| Topic tags | `video_tags`, `kind = topic` | Watch page and search |
| Moderation flags | `video_tags`, `kind = moderation` | Staff only: filter by kind at `/admin/intelligence/videotag/` |
| Thumbnail | Replaces `thumbnails/{id}/default.jpg` | Everyone |

- **Search:** `GET /api/search/?q=...` uses PostgreSQL full-text search over ready videos: title, then description,
  tags and speech, in that order of weight. It supports `"exact phrases"`, `or` and `-excluded`. The document is built
  per query, which suits an MVP catalogue. A stored `tsvector` with a GIN index is the next step as it grows.
- **Flags only queue a video for review.** They never hide it, and viewers can't see or search them. A flagged video
  keeps the encoder's thumbnail.
- **Failures:** two attempts, then `video.ready.ml.dlq`. Such a video simply has no analysis.

**Measured** with the real models on 2 CPU cores and a 3 GB limit, November 2026:

- **Speech (Whisper `base`):** a 203-second lecture took 16 seconds (13× real time), and an 11-second speech came out
  word for word. Noise, silence, a tone and a synthetic chord produced no text at all. Peak memory was about 1 GB.
- **Topics (CLIP):** of 16 photos held out from the first round of tuning, 13 got the right tag, 2 got none and 1 got a
  wrong one (a group of people became `education`). Ordinary objects mostly get no tag, but a pair of shoes became
  `cooking`.
- **Moderation:** the first labels flagged food and a piano as `nudity`, so food and object labels were added. Now
  none of 33 harmless photos is flagged and a photo of a rifle still is. A video is flagged on its worst frame, so
  more frames mean more chances of a false alarm.
- **Thumbnails:** eight bad frames (black, white, grey, test card, dark, faded, blurred, washed out) scored at most
  0.07 and 79% of 34 real photos cleared the cutoff of 0.1. A lecture opening on black got a real frame instead.

**Known limits:**

- **Moderation is largely unproven.** It was only tested for false alarms and on one weapon photo. Nudity and violence
  were never tested on real examples. Don't rely on it to catch anything: human review and a purpose-built service
  are needed before this handles public uploads. One photo (the shoes) sits just under the flag cutoff, at 0.699.
- **The photo sets are small, and the moderation labels were tuned on all 33 harmless photos,** so its false-alarm
  figure is optimistic.
- **Thumbnails come from the lowest rendition** and replace the encoder's at the same key, so a browser that cached
  the old one shows it until the cache expires.
- **Long videos:** only the first hour is transcribed (`ML_MAX_TRANSCRIBE_SEC`).
- **Similar videos:** the 0.2 cutoff was measured on titles, not on text that includes speech, so it needs measuring
  again once there are real videos with speech.

## Operations

- **Logs:** every service writes one JSON object per line (`LOG_FORMAT=text` for readable local output),
  ready for CloudWatch Logs.
- **Correlation ID:** nginx gives each request an `X-Request-ID`, replacing any the client sent. Django
  logs it and returns it. Kafka events carry it as `correlation_id`, and consumers and the encoder log
  under it, so one upload can be followed from `/complete` through encoding to the status update:

  ```sh
  docker compose logs --no-log-prefix | grep <request_id>
  ```

- **Health:**
  - `/api/health/` is liveness (database only), for Docker and the load balancer.
  - `/api/health/ready/` checks Postgres, MongoDB, Kafka and S3, for deploy smoke tests. Only staff see
    error details.
- **Monitoring:** the `monitor` service logs consumer lag per group and the DLQ size every minute. It
  warns when a group's lag stays above 100 for two checks in a row, or when the DLQ grows. With
  `CLOUDWATCH_NAMESPACE` set, it also pushes `ConsumerLag` and `DeadLetterMessages` metrics for
  CloudWatch alarms. One-off snapshot: `docker compose exec django python manage.py monitor --once`.
- **Errors:** set `SENTRY_DSN` (Django, consumers, encoder) and the `VITE_SENTRY_DSN` build argument
  (browser). Without them, Sentry isn't loaded at all. PII sending is off.

## Security

| Checklist item (blueprint §11) | Where |
|---|---|
| HTTPS everywhere | `config/settings/prod.py`: SSL redirect (health checks exempt), HSTS, secure cookies; TLS at nginx / load balancer and CloudFront |
| Access token in memory, refresh token in an httpOnly cookie, rotation + blacklist | `accounts/views.py`, `app/api.ts` |
| Rate limits | nginx (`auth` 10/min, `api` 20/s) and DRF scopes (`auth`, `upload` 30/h, `events` 120/min) |
| Validate uploads, ffprobe in the worker | `videos/serializers.py`, `worker/encoder/probe.py` |
| Private bucket, OAC, signed cookies | `infra/terraform/media`, `videos/playback.py` |
| Least-privilege IAM, no keys in code or images | Phase 6 part B (Terraform roles); `.env` stays out of git and images |
| Owner-only edits and deletes | `VideoViewSet.get_owned_object` (tested) |
| Dependency and image scanning | `.github/dependabot.yml`; Trivy fails CI on fixable CRITICAL/HIGH issues |

Also:
- The app pages get a strict Content-Security-Policy (no inline or eval'd scripts) and security headers
  from nginx. Set `CSP_MEDIA_ORIGINS` and `CSP_UPLOAD_ORIGINS` per environment.
- CI runs `manage.py check --deploy` against the production settings.
- All app containers run as non-root.

## Development

Backend tests and lint (no local Python setup needed):

```sh
docker run --rm -v "$PWD/backend:/app" -w /app python:3.12-slim \
  sh -c "pip install -q -r requirements-dev.txt && ruff check . && pytest -q"
```

Worker tests (real FFmpeg; the claim tests also need the running Postgres):

```sh
docker build --target base -t streaming-worker-test ./worker
docker run --rm --network youtube_default -e POSTGRES_HOST=postgres -e POSTGRES_PASSWORD=<from .env> \
  -v "$PWD/worker:/app" -w /app streaming-worker-test \
  sh -c "pip install -q -r requirements-dev.txt && ruff check . && pytest -q"
```

Frontend checks:

```sh
docker run --rm -v "$PWD/frontend:/app" -w /app node:22-alpine \
  sh -c "npm ci && npm run lint && npm run typecheck && npm test"
```

With Node installed locally, `cd frontend && npm install && npm run dev` gives hot reload on
http://localhost:5173. It proxies `/api` to the Docker stack on :8080.

CI (`.github/workflows/ci.yml`) runs ruff, a migrations check and pytest against Postgres and Kafka, ESLint, tsc and
Vitest, then builds and scans every Docker image.

## Deviations from the blueprint

- **MongoDB and subscribers arrived in Phase 5, not Phase 1** (lean MVP, as the blueprint's "ways to go faster"
  suggests). The stack now matches the blueprint.
- **SeaweedFS instead of MinIO** for local S3. MinIO no longer publishes community Docker images.
  Both speak the S3 API, so boto3 code is the same. SeaweedFS ignores bucket lifecycle rules, which
  only take effect on real S3.
- **Multipart part URLs last 2 hours** (single-PUT URLs last 15 minutes), so large uploads on slow
  connections don't expire partway through.

- **The encoder skips duplicates instead of every `processing` video.** Skipping all `processing` videos
  would leave a video stuck forever after a worker crash. The `event_id` check handles both cases.
- **CloudFront runs locally as a small Python stand-in** (`infra/local-cdn`) that checks the same signed
  cookies. nginx can't verify RSA signatures. It checks cookies independently of Django's signer, so each
  tests the other.

- **`keepalive` fetch instead of `sendBeacon`** for the final flush (see above). `sendBeacon` remains the
  fallback.
- **Kafka over TLS on MSK** (`KAFKA_SECURITY_PROTOCOL=SSL`). Locally it stays plaintext.
- **`fastembed` instead of `sentence-transformers`:** same model, without PyTorch's memory and image size.
- **Collaborative filtering and MLflow (step 51) aren't built yet.** The blueprint says to wait for a few thousand
  users with real watch history, because on sparse data it does worse than popularity.
- **`faster-whisper` and `fastembed` instead of PyTorch Whisper and CLIP:** the same models through CTranslate2 and
  ONNX, on a CPU, with a much smaller image and memory use. The blueprint suggests a GPU only once volume grows.
- **Time-based keyframes instead of `-g 48`:** a keyframe every 2 seconds stays aligned across renditions at any frame
  rate, whereas 48 frames is only 2 seconds at 24 fps.
- **Deleting a video cleans S3 during the request, not through an event.** The blueprint's endpoint table says "via
  event", but its topic table has no such topic. If S3 fails, the API returns 503 and the video stays, so nothing is
  orphaned. A video with many files makes the request slower.
- **Layout and naming:** `run_consumer <name>` instead of one command per consumer, notify and feed as separate
  containers, the silent token refresh in the axios interceptor rather than `authSaga` (same single-refresh lock), and
  `VideoGrid` instead of `VideoCard`. Behaviour is the same.

**Not built yet:**

- **Comments:** the data model lists a MongoDB `comments` collection, but no endpoint, page or checklist step covers it.
- **Jupyter container (section 12.3)** and **the rest of Phase 10**.
- **Monitoring:** lag, DLQ, 5xx and health alarms exist. Encoding duration is only in the logs, and API latency, encoding
  failure rate and CloudFront cache hit ratio have no dashboard or alarm.

## Deployment (AWS)

Everything for AWS is in the repository but **has not been applied to any account**. The
[runbook](docs/runbook.md) walks through first-time setup, deploys, rollback and operations. In short:

- `infra/terraform/bootstrap`: once per account. State bucket, ECR, releases bucket, GitHub OIDC.
- `infra/terraform/app`: one environment per state (`-var-file=staging.tfvars` / `production.tfvars`).
  VPC, load balancer with TLS, EC2 hosts, RDS, MSK, IAM, config and secrets, logs and alarms, plus the
  S3 + CloudFront media module.
- `.github/workflows/deploy.yml`: green `main` → images to ECR → staging → full smoke test → approval →
  production. Manual re-run with an older SHA for rollback.
- `deploy/smoke.py` works against any environment, including this local stack:

  ```sh
  SMOKE_EMAIL=... SMOKE_PASSWORD=... python3 deploy/smoke.py --base-url http://localhost:8080 --full
  ```

Checks that run without AWS: `sh infra/terraform/check.sh` (fmt + validate), Trivy's config scan, the
`deploy/tests` unit tests and shellcheck. CI runs all of them.

## Next

- **Apply Part B to a real AWS account:** needs your go-ahead and credentials. It costs money (see the
  runbook).
- **Phase 10:** big data and real time (Kafka Connect to an S3 Parquet lake, PySpark jobs, Flink metrics).
