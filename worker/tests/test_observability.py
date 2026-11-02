import json
import logging

from encoder import logs, messaging
from encoder.main import run_while_polling


class IdleConsumer:
    """Stands in for confluent_kafka.Consumer while a job runs: nothing new arrives."""

    def __init__(self):
        self.paused = self.resumed = 0

    def assignment(self):
        return []

    def pause(self, partitions):
        self.paused += 1

    def resume(self, partitions):
        self.resumed += 1

    def poll(self, timeout):
        return None


def test_job_thread_sees_the_correlation_id_and_publishes_with_it(monkeypatch, tmp_path):
    monkeypatch.setattr("encoder.config.HEARTBEAT_FILE", str(tmp_path / "hb"))
    consumer = IdleConsumer()
    token = logs.correlation_id.set("req-42")
    try:
        seen = run_while_polling(
            consumer, lambda: (logs.correlation_id.get(), messaging.build_event("video.ready", {}))
        )
    finally:
        logs.correlation_id.reset(token)
    in_thread, event = seen
    assert in_thread == "req-42"
    assert event["correlation_id"] == "req-42"
    assert consumer.paused == consumer.resumed == 1


def test_json_formatter():
    record = logging.LogRecord("encoder", logging.INFO, __file__, 1, "video %s ready", ("abc",), None)
    token = logs.correlation_id.set("req-1")
    try:
        entry = json.loads(logs.JsonFormatter().format(record))
    finally:
        logs.correlation_id.reset(token)
    assert entry["message"] == "video abc ready" and entry["correlation_id"] == "req-1"
