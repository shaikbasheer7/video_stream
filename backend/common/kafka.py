"""Kafka producer helper. Every message carries event, event_id, occurred_at and schema_version."""

import json
import logging
import time
import uuid
from datetime import UTC, datetime
from functools import cache
from pathlib import Path

from confluent_kafka import Consumer, KafkaException, Producer, TopicPartition
from django.conf import settings
from django.db import close_old_connections

from .logs import correlation_id

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

VIDEO_UPLOADED = "video.uploaded"
VIDEO_READY = "video.ready"
VIDEO_FAILED = "video.failed"
VIDEO_UPLOADED_DLQ = "video.uploaded.dlq"
VIDEO_READY_ML_DLQ = "video.ready.ml.dlq"
EVENTS_PLAYBACK = "events.playback"
ALL_TOPICS = [VIDEO_UPLOADED, VIDEO_READY, VIDEO_FAILED, VIDEO_UPLOADED_DLQ, VIDEO_READY_ML_DLQ, EVENTS_PLAYBACK]


class PublishError(Exception):
    pass


def client_config(**extra):
    """Connection settings shared by every Kafka client (producer, consumers, admin).

    Locally Kafka is plaintext; on AWS MSK the brokers require TLS (KAFKA_SECURITY_PROTOCOL=SSL).
    """
    config = {
        "bootstrap.servers": settings.KAFKA_BOOTSTRAP_SERVERS,
        "security.protocol": settings.KAFKA_SECURITY_PROTOCOL,
    }
    if settings.KAFKA_SECURITY_PROTOCOL == "SSL":
        config["ssl.ca.location"] = settings.KAFKA_SSL_CA_LOCATION
    return {**config, **extra}


@cache
def producer():
    return Producer(client_config(**{"acks": "all", "enable.idempotence": True, "message.timeout.ms": 10_000}))


def build_event(event, payload):
    event_id = str(uuid.uuid4())
    return {
        "event": event,
        "event_id": event_id,
        # Inherited from the request/message being handled, so one upload can be traced end to end.
        "correlation_id": correlation_id.get() or event_id,
        "occurred_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        **payload,
        "schema_version": SCHEMA_VERSION,
    }


def publish(topic, key, payload, event=None, timeout=10.0):
    """Publish one event and wait for the broker to acknowledge it. Raises PublishError on failure."""
    message = build_event(event or topic, payload)
    errors = []

    def on_delivery(err, _msg):
        if err is not None:
            errors.append(err)

    p = producer()
    try:
        p.produce(
            topic, key=str(key).encode(), value=json.dumps(message, default=str).encode(), on_delivery=on_delivery
        )
    except BufferError as exc:
        raise PublishError(str(exc)) from exc
    if p.flush(timeout) > 0 or errors:
        logger.error("Kafka publish to %s failed: %s", topic, errors or "flush timeout")
        raise PublishError(f"Could not publish {message['event']}")
    return message


def publish_many(topic, messages, event=None, timeout=10.0):
    """Publish (key, payload) pairs with one flush. Raises PublishError if any fails."""
    errors = []

    def on_delivery(err, _msg):
        if err is not None:
            errors.append(err)

    p = producer()
    try:
        for key, payload in messages:
            message = build_event(event or topic, payload)
            p.produce(
                topic, key=str(key).encode(), value=json.dumps(message, default=str).encode(), on_delivery=on_delivery
            )
    except BufferError as exc:
        raise PublishError(str(exc)) from exc
    if p.flush(timeout) > 0 or errors:
        logger.error("Kafka publish_many to %s failed: %s", topic, errors or "flush timeout")
        raise PublishError(f"Could not publish to {topic}")


def run_consumer(topics, group_id, handler, should_stop, heartbeat_file=None, retry_delay=5.0):
    """At-least-once consumer loop: offsets are committed only after handler(event) returns.

    If the handler raises (database down, etc.) the message is retried after retry_delay.
    Handlers must be idempotent and should swallow errors that a retry cannot fix.
    """
    consumer = Consumer(
        client_config(**{"group.id": group_id, "enable.auto.commit": False, "auto.offset.reset": "earliest"})
    )
    consumer.subscribe(topics)
    logger.info("consuming %s as group %s", topics, group_id)
    try:
        while not should_stop():
            if heartbeat_file:
                Path(heartbeat_file).touch()
            msg = consumer.poll(1.0)
            if msg is None:
                continue
            if msg.error():
                logger.warning("consumer error: %s", msg.error())
                continue
            try:
                event = json.loads(msg.value())
            except ValueError:
                logger.error("unreadable message at %s[%d]@%d, skipping", msg.topic(), msg.partition(), msg.offset())
                consumer.commit(message=msg, asynchronous=False)
                continue

            close_old_connections()  # long-running process: drop connections the DB has closed
            token = correlation_id.set(str(event.get("correlation_id") or event.get("event_id") or "") or None)
            try:
                handler(event)
            except Exception:
                logger.exception("handler failed for %s[%d]@%d, retrying", msg.topic(), msg.partition(), msg.offset())
                consumer.seek(TopicPartition(msg.topic(), msg.partition(), msg.offset()))
                time.sleep(retry_delay)
                continue
            finally:
                correlation_id.reset(token)
            try:
                consumer.commit(message=msg, asynchronous=False)
            except KafkaException as exc:
                logger.warning("commit failed (rebalance?): %s", exc)
    finally:
        consumer.close()
