"""The Kafka helpers against a real broker. CI runs one as a service container.

Locally: KAFKA_INTEGRATION=1 with KAFKA_BOOTSTRAP_SERVERS pointing at a broker.
"""

import os
import time
import uuid

import pytest
from confluent_kafka.admin import AdminClient, NewTopic

from common import kafka

pytestmark = pytest.mark.skipif(not os.environ.get("KAFKA_INTEGRATION"), reason="needs a Kafka broker")

TIMEOUT_SEC = 60


@pytest.fixture
def topic():
    admin = AdminClient(kafka.client_config())
    name = f"test.{uuid.uuid4()}"
    admin.create_topics([NewTopic(name, num_partitions=1, replication_factor=1)])[name].result(30)
    yield name
    admin.delete_topics([name])[name].result(30)


def consume(topic, group, handler, until):
    """Run the real consumer loop until `until()` is true. Fails rather than hanging if it never is."""
    deadline = time.monotonic() + TIMEOUT_SEC

    def should_stop():
        return until() or time.monotonic() > deadline

    kafka.run_consumer([topic], group, handler, should_stop=should_stop, retry_delay=0)
    assert until(), "timed out waiting for the broker"


def test_a_published_event_arrives_with_its_envelope(topic):
    kafka.publish(topic, key="video-1", payload={"video_id": "video-1"}, event="video.ready")

    seen = []
    consume(topic, f"group-{uuid.uuid4()}", seen.append, until=lambda: seen)

    event = seen[0]
    assert (event["event"], event["video_id"], event["schema_version"]) == ("video.ready", "video-1", 1)
    assert event["event_id"] and event["occurred_at"]


def test_offsets_are_committed_only_after_the_handler_succeeds(topic):
    group = f"group-{uuid.uuid4()}"
    kafka.publish(topic, key="v", payload={"n": 1})

    attempts = []

    def fails_once(event):
        attempts.append(event["event_id"])
        if len(attempts) == 1:
            raise RuntimeError("database down")

    consume(topic, group, fails_once, until=lambda: len(attempts) == 2)
    assert attempts[0] == attempts[1]  # the same message again, not the next one

    # The same group resumes after the handled message, so a restart doesn't redo finished work.
    kafka.publish(topic, key="v", payload={"n": 2})
    seen = []
    consume(topic, group, seen.append, until=lambda: seen)
    assert seen[0]["n"] == 2
