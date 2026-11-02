# syntax=docker/dockerfile:1
# Separate from the encoder's image: this one carries the speech and vision models (well over 1 GB).
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    ML_MODELS_DIR=/opt/models
# Not version-pinned on purpose: see worker/Dockerfile.
# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app

FROM base AS deps
COPY requirements.txt requirements-ml.txt ./
RUN pip install -r requirements-ml.txt

FROM deps AS models
COPY encoder ./encoder
COPY ml ./ml
RUN python -m ml.download_models && chmod -R a+rX /opt/models

FROM deps AS runtime
RUN useradd --create-home --uid 1000 app
COPY --from=models /opt/models /opt/models
COPY encoder ./encoder
COPY ml ./ml
# Nothing may be fetched at runtime: a missing model is an error, not a surprise download.
ENV HF_HUB_OFFLINE=1
USER app
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import os, sys, time; sys.exit(time.time() - os.path.getmtime('/tmp/heartbeat') > 120)"
CMD ["python", "-m", "ml.main"]
