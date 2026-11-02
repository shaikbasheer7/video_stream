import json
import logging

import pytest
from rest_framework.test import APIClient

from accounts.models import User
from common import health, kafka
from common.lag import NO_OFFSET, compute_lag
from common.logs import CorrelationIdFilter, JsonFormatter, correlation_id
from common.management.commands.monitor import evaluate, to_metric_data


def format_record(message, **extra):
    record = logging.LogRecord("app", logging.WARNING, __file__, 1, message, (), None)
    record.__dict__.update(extra)
    CorrelationIdFilter().filter(record)
    return json.loads(JsonFormatter().format(record))


def test_json_log_lines_include_level_fields_and_correlation_id():
    token = correlation_id.set("req-123")
    try:
        entry = format_record("video %s ready", video_id="abc")
    finally:
        correlation_id.reset(token)
    assert entry["level"] == "WARNING" and entry["logger"] == "app"
    assert entry["correlation_id"] == "req-123" and entry["video_id"] == "abc"
    assert entry["ts"].endswith("+00:00")


@pytest.mark.django_db
def test_request_id_is_taken_from_nginx_or_generated_and_echoed():
    client = APIClient()
    assert client.get("/api/health/", HTTP_X_REQUEST_ID="abc123").headers["X-Request-ID"] == "abc123"
    generated = client.get("/api/health/", HTTP_X_REQUEST_ID="bad id\nwith newline").headers["X-Request-ID"]
    assert len(generated) == 32 and "\n" not in generated


def test_events_inherit_the_current_correlation_id():
    token = correlation_id.set("req-9")
    try:
        assert kafka.build_event("video.uploaded", {})["correlation_id"] == "req-9"
    finally:
        correlation_id.reset(token)
    standalone = kafka.build_event("video.uploaded", {})
    assert standalone["correlation_id"] == standalone["event_id"]


@pytest.mark.django_db
def test_readiness_reports_each_dependency(monkeypatch):
    def broken():
        raise ConnectionError("broker unreachable")

    monkeypatch.setattr(health, "CHECKS", {"postgres": health.check_postgres, "kafka": broken})
    response = APIClient().get("/api/health/ready/")
    assert response.status_code == 503
    assert response.data["status"] == "degraded"
    assert response.data["checks"] == {"postgres": {"ok": True}, "kafka": {"ok": False}}  # no details for the public

    staff = User.objects.create_user(email="ops@example.com", password="pw-123456789", is_staff=True)
    client = APIClient()
    client.force_authenticate(staff)
    detail = client.get("/api/health/ready/").data["checks"]["kafka"]
    assert "broker unreachable" in detail["error"] and "ms" in detail

    monkeypatch.setattr(health, "CHECKS", {"postgres": health.check_postgres})
    assert APIClient().get("/api/health/ready/").status_code == 200


def test_lag_counts_waiting_messages_including_never_committed_partitions():
    partitions = [("t", 0), ("t", 1), ("t", 2)]
    watermarks = {("t", 0): (0, 100), ("t", 1): (10, 50), ("t", 2): (0, 7)}
    committed = {("t", 0): 90, ("t", 1): NO_OFFSET, ("t", 2): 7}
    assert compute_lag(partitions, committed, watermarks) == 10 + 40 + 0


def test_alerts_on_sustained_lag_and_dlq_growth_only():
    quiet = {"lag": {"encoder": 5}, "dlq_messages": 2}
    spike = {"lag": {"encoder": 500}, "dlq_messages": 2}
    assert evaluate(None, spike, 100) == []  # one high reading: no alert yet
    assert evaluate(spike, spike, 100) == ["consumer group encoder lag 500 (was 500) is above 100"]
    assert evaluate(quiet, {"lag": {"encoder": 5}, "dlq_messages": 3}, 100) == [
        "1 new message(s) in the dead-letter queue"
    ]
    assert evaluate(quiet, quiet, 100) == []


def test_throttles_key_on_the_client_ip_nginx_forwards():
    from rest_framework.test import APIRequestFactory
    from rest_framework.throttling import ScopedRateThrottle
    from rest_framework.views import APIView

    factory = APIRequestFactory()
    throttle = ScopedRateThrottle()
    # nginx appends the client (after resolving the load balancer's X-Forwarded-For) as the last entry.
    behind_nginx = APIView().initialize_request(
        factory.get("/", HTTP_X_FORWARDED_FOR="203.0.113.7", REMOTE_ADDR="172.18.0.5")
    )
    assert throttle.get_ident(behind_nginx) == "203.0.113.7"
    spoofed = APIView().initialize_request(
        factory.get("/", HTTP_X_FORWARDED_FOR="1.2.3.4, 203.0.113.7", REMOTE_ADDR="172.18.0.5")
    )
    assert throttle.get_ident(spoofed) == "203.0.113.7"  # a client-supplied prefix is ignored


def test_kafka_clients_use_tls_when_configured(settings):
    from common.kafka import client_config

    settings.KAFKA_SECURITY_PROTOCOL = "PLAINTEXT"
    assert "ssl.ca.location" not in client_config()
    settings.KAFKA_SECURITY_PROTOCOL = "SSL"
    config = client_config(**{"group.id": "g"})
    assert config["security.protocol"] == "SSL" and config["ssl.ca.location"] == "probe" and config["group.id"] == "g"


def test_infra_commands_load_and_the_data_stack_is_optional(settings):
    from django.core.management import load_command_class

    from common.analytics_access import ensure_analytics_access

    assert load_command_class("common", "ensure_infra") is not None
    assert load_command_class("common", "run_consumer") is not None
    assert load_command_class("common", "monitor") is not None
    settings.ANALYTICS_ETL_PASSWORD = ""
    assert ensure_analytics_access() is False  # AWS has no data stack yet: nothing to create


def test_cloudwatch_metric_shape():
    data = to_metric_data({"lag": {"encoder": 3}, "dlq_messages": 1})
    assert data == [
        {"MetricName": "ConsumerLag", "Dimensions": [{"Name": "ConsumerGroup", "Value": "encoder"}], "Value": 3},
        {"MetricName": "DeadLetterMessages", "Value": 1},
    ]
