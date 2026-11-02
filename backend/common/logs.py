"""Structured JSON logs (one object per line, for CloudWatch Logs) with a correlation id.

The correlation id is the request id for HTTP requests (taken from nginx's X-Request-ID, echoed back in
the response) and the event_id for Kafka messages, so one upload can be followed across services.
"""

import json
import logging
import os
import re
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime

correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)

SERVICE = os.environ.get("SERVICE_NAME", "django")
_VALID_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
# Attributes every LogRecord has; anything else was passed via `extra=` and is logged as a field.
_STANDARD = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime", "correlation_id"}


class CorrelationIdFilter(logging.Filter):
    def filter(self, record):
        record.correlation_id = correlation_id.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record):
        entry = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "service": SERVICE,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if getattr(record, "correlation_id", None):
            entry["correlation_id"] = record.correlation_id
        for key, value in record.__dict__.items():
            if key not in _STANDARD and not key.startswith("_"):
                entry[key] = value
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


class RequestIdMiddleware:
    """Use nginx's request id (or make one), expose it to logs and return it to the client."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        incoming = request.headers.get("X-Request-ID", "")
        request_id = incoming if _VALID_ID.match(incoming) else uuid.uuid4().hex
        request.request_id = request_id
        token = correlation_id.set(request_id)
        try:
            response = self.get_response(request)
        finally:
            correlation_id.reset(token)
        response["X-Request-ID"] = request_id
        return response
