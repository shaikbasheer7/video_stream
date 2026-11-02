import os
from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def env_bool(name, default=False):
    return os.environ.get(name, str(default)).lower() in ("1", "true", "yes")


def env_list(name, default=""):
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
DEBUG = env_bool("DJANGO_DEBUG")
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "accounts",
    "common",
    "videos",
    "events",
    "notifications",
    "social",
    "analytics",
    "recommendations",
    "intelligence",
]

MIDDLEWARE = [
    "common.logs.RequestIdMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# PostgreSQL when POSTGRES_HOST is set (Docker, CI, prod); SQLite otherwise for quick local runs.
if os.environ.get("POSTGRES_HOST"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "HOST": os.environ["POSTGRES_HOST"],
            "PORT": os.environ.get("POSTGRES_PORT", "5432"),
            "NAME": os.environ.get("POSTGRES_DB", "streaming"),
            "USER": os.environ.get("POSTGRES_USER", "streaming"),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
            "CONN_MAX_AGE": 60,
        }
    }
else:
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# JWT for the API only; Django admin keeps its own session auth.
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework_simplejwt.authentication.JWTAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    # Only views that set throttle_scope are throttled.
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.ScopedRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {
        "auth": os.environ.get("AUTH_THROTTLE_RATE", "10/min"),
        "upload": os.environ.get("UPLOAD_THROTTLE_RATE", "30/hour"),
        "events": os.environ.get("EVENTS_THROTTLE_RATE", "120/min"),
        "search": os.environ.get("SEARCH_THROTTLE_RATE", "60/min"),
    },
    # Django always sits behind nginx, which puts the real client IP last in X-Forwarded-For;
    # throttles key on it instead of nginx's own address.
    "NUM_PROXIES": 1,
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "SIGNING_KEY": SECRET_KEY,
}

# Refresh token cookie, readable only by /api/auth/ endpoints.
REFRESH_COOKIE_NAME = "refresh_token"
REFRESH_COOKIE_PATH = "/api/auth/"
REFRESH_COOKIE_SECURE = env_bool("REFRESH_COOKIE_SECURE", True)
REFRESH_COOKIE_SAMESITE = "Lax"

CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS")
CORS_ALLOW_CREDENTIALS = True

# S3. S3_ENDPOINT_URL is how services reach storage; S3_PUBLIC_ENDPOINT_URL is what browsers
# see in presigned URLs. Both are empty on real AWS.
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
S3_BUCKET = os.environ.get("S3_BUCKET", "streaming-media")
S3_ENDPOINT_URL = os.environ.get("S3_ENDPOINT_URL") or None
S3_PUBLIC_ENDPOINT_URL = os.environ.get("S3_PUBLIC_ENDPOINT_URL") or S3_ENDPOINT_URL
S3_ADDRESSING_STYLE = os.environ.get("S3_ADDRESSING_STYLE", "auto")
S3_CORS_ORIGINS = env_list("S3_CORS_ORIGINS")

# Uploads: single presigned PUT up to the threshold, S3 multipart above it.
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", 5 * 1024**3))
MULTIPART_THRESHOLD_BYTES = 100 * 1024**2
MULTIPART_PART_BYTES = 16 * 1024**2
UPLOAD_URL_EXPIRES = 15 * 60
MULTIPART_URL_EXPIRES = 2 * 60 * 60  # large files on slow links need longer than 15 min

# Playback through the CDN (CloudFront in AWS; infra/local-cdn locally) with signed cookies
# scoped to one video's HLS folder.
CDN_BASE_URL = os.environ.get("CDN_BASE_URL", "http://localhost:8080/cdn").rstrip("/")
CDN_COOKIE_DOMAIN = os.environ.get("CDN_COOKIE_DOMAIN") or None  # e.g. ".example.com" when the CDN is a subdomain
CDN_COOKIE_SECURE = env_bool("CDN_COOKIE_SECURE", True)
CLOUDFRONT_KEY_PAIR_ID = os.environ.get("CLOUDFRONT_KEY_PAIR_ID", "")
CLOUDFRONT_PRIVATE_KEY = os.environ.get("CLOUDFRONT_PRIVATE_KEY", "")  # PEM (from Secrets Manager in AWS)
CLOUDFRONT_PRIVATE_KEY_PATH = os.environ.get("CLOUDFRONT_PRIVATE_KEY_PATH", "")  # or a mounted file
PLAYBACK_MIN_TTL_SEC = 2 * 60 * 60
PLAYBACK_MAX_TTL_SEC = 12 * 60 * 60

# MongoDB: high-volume, append-mostly data (playback events, watch progress, notifications, feeds).
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
MONGO_DB = os.environ.get("MONGO_DB", "streaming")
EVENTS_TTL_DAYS = int(os.environ.get("EVENTS_TTL_DAYS", 90))

# Data stack (Airflow + Superset). Roles are only created when these are set (see common/analytics_access.py).
ANALYTICS_ETL_PASSWORD = os.environ.get("ANALYTICS_ETL_PASSWORD", "")
ANALYTICS_RO_PASSWORD = os.environ.get("ANALYTICS_RO_PASSWORD", "")
ML_WORKER_DB_PASSWORD = os.environ.get("ML_WORKER_DB_PASSWORD", "")

KAFKA_BOOTSTRAP_SERVERS = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:29092")
KAFKA_SECURITY_PROTOCOL = os.environ.get("KAFKA_SECURITY_PROTOCOL", "PLAINTEXT")  # SSL on AWS MSK
KAFKA_SSL_CA_LOCATION = os.environ.get("KAFKA_SSL_CA_LOCATION", "probe")  # system CA bundle
KAFKA_TOPIC_PARTITIONS = int(os.environ.get("KAFKA_TOPIC_PARTITIONS", 6))
KAFKA_REPLICATION_FACTOR = int(os.environ.get("KAFKA_REPLICATION_FACTOR", 1))

# JSON lines by default (CloudWatch Logs); LOG_FORMAT=text for readable local output.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"correlation": {"()": "common.logs.CorrelationIdFilter"}},
    "formatters": {
        "json": {"()": "common.logs.JsonFormatter"},
        "text": {"format": "%(asctime)s %(levelname)s %(name)s [%(correlation_id)s] %(message)s"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": os.environ.get("LOG_FORMAT", "json"),
            "filters": ["correlation"],
        }
    },
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
    "loggers": {
        # nginx writes the access log; Django's own request log would duplicate it.
        "django.server": {"level": "WARNING"},
        # Noisy at INFO (e.g. "Found credentials in environment variables").
        "botocore": {"level": "WARNING"},
        "pymongo": {"level": "WARNING"},
    },
}

# Error tracking: enabled only when SENTRY_DSN is set.
SENTRY_DSN = os.environ.get("SENTRY_DSN", "")
if SENTRY_DSN:
    import sentry_sdk

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        environment=os.environ.get("SENTRY_ENVIRONMENT", "development"),
        release=os.environ.get("GIT_SHA") or None,
        traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", 0.05)),
        send_default_pii=False,  # no emails/IPs in error reports
    )
