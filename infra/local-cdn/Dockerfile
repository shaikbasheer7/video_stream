# syntax=docker/dockerfile:1
# Local development only: stands in for CloudFront. Not deployed.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN pip install boto3==1.40.0 cryptography==45.0.7 \
    && useradd --create-home --uid 1000 app
WORKDIR /app
COPY cdn.py .
USER app
EXPOSE 8090
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/healthz', timeout=2)"
CMD ["python", "cdn.py"]
