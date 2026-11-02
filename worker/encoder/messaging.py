"""Kafka producer with the same message envelope as backend/common/kafka.py."""

import json
import uuid
from datetime import UTC, datetime
from functools import cache

from confluent_kafka import Producer

from . import config
from .logs import correlation_id

SCHEMA_VERSION = 1
VIDEO_UPLOADED = "video.uploaded"
VIDEO_READY = "video.ready"
VIDEO_FAILED = "video.failed"
VIDEO_UPLOADED_DLQ = "video.uploaded.dlq"


class PublishError(Exception):
    pass


@cache
def producer():
    return Producer(config.kafka_config(**{"acks": "all", "enable.idempotence": True, "message.timeout.ms": 30_000}))


def build_event(event, payload):
    event_id = str(uuid.uuid4())
    return {
        "event": event,
        "event_id": event_id,
        "correlation_id": correlation_id.get() or event_id,  # carried over from video.uploaded
        "occurred_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        **payload,
        "schema_version": SCHEMA_VERSION,
    }


def publish(topic, key, payload, timeout=30.0):
    message = build_event(topic, payload)
    errors = []
    p = producer()
    p.produce(
        topic,
        key=str(key).encode(),
        value=json.dumps(message, default=str).encode(),
        on_delivery=lambda err, _msg: err and errors.append(err),
    )
    if p.flush(timeout) > 0 or errors:
        raise PublishError(f"Could not publish {topic}: {errors or 'flush timeout'}")
    return message
