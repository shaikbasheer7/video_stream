import os

GROUP_ID = os.environ.get("ML_GROUP_ID", "ml")
MODELS_DIR = os.environ.get("ML_MODELS_DIR", "/opt/models")  # baked into the image at build time
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "base")
CPU_THREADS = int(os.environ.get("ML_CPU_THREADS", 2))
MAX_ATTEMPTS = int(os.environ.get("ML_MAX_ATTEMPTS", 2))
RETRY_BACKOFF_SEC = float(os.environ.get("ML_RETRY_BACKOFF_SEC", 5))
# Speech recognition on a CPU costs minutes per hour of video: only this much of each video gets transcribed.
MAX_TRANSCRIBE_SEC = int(os.environ.get("ML_MAX_TRANSCRIBE_SEC", 60 * 60))
FRAMES_PER_VIDEO = int(os.environ.get("ML_FRAMES_PER_VIDEO", 8))
