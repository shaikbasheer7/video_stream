import os

KAFKA_BOOTSTRAP_SERVERS = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:29092")
GROUP_ID = os.environ.get("ENCODER_GROUP_ID", "encoder")

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
S3_BUCKET = os.environ.get("S3_BUCKET", "streaming-media")
S3_ENDPOINT_URL = os.environ.get("S3_ENDPOINT_URL") or None
S3_ADDRESSING_STYLE = os.environ.get("S3_ADDRESSING_STYLE", "auto")

DATABASE = {
    "host": os.environ.get("POSTGRES_HOST", "localhost"),
    "port": int(os.environ.get("POSTGRES_PORT", 5432)),
    "dbname": os.environ.get("POSTGRES_DB", "streaming"),
    "user": os.environ.get("POSTGRES_USER", "streaming"),
    "password": os.environ.get("POSTGRES_PASSWORD", ""),
}

MAX_ATTEMPTS = int(os.environ.get("ENCODE_MAX_ATTEMPTS", 3))
RETRY_BACKOFF_SEC = float(os.environ.get("ENCODE_RETRY_BACKOFF_SEC", 5))
# MVP guard against very long (expensive) encodes.
MAX_DURATION_SEC = float(os.environ.get("MAX_VIDEO_DURATION_SEC", 2 * 60 * 60))
HEARTBEAT_FILE = os.environ.get("HEARTBEAT_FILE", "/tmp/heartbeat")
