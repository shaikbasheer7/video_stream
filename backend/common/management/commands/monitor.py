"""Periodic platform metrics: consumer lag per group and DLQ size.

Every check is written as one JSON log line (CloudWatch Logs metric filters can alarm on them). With
CLOUDWATCH_NAMESPACE set, the numbers are also pushed as CloudWatch metrics.

Warnings are logged when lag stays above the threshold for two checks in a row, or the DLQ grows.
"""

import logging
import os
import signal
import time

from django.core.management.base import BaseCommand

from common.lag import KafkaInspector

logger = logging.getLogger("monitor")


def evaluate(previous, current, lag_threshold):
    """Return alert messages comparing two snapshots."""
    alerts = []
    for group, lag in current["lag"].items():
        before = (previous or {}).get("lag", {}).get(group, 0)
        if lag > lag_threshold and before > lag_threshold:
            alerts.append(f"consumer group {group} lag {lag} (was {before}) is above {lag_threshold}")
    if previous is not None and current["dlq_messages"] > previous["dlq_messages"]:
        new = current["dlq_messages"] - previous["dlq_messages"]
        alerts.append(f"{new} new message(s) in the dead-letter queue")
    return alerts


class Command(BaseCommand):
    help = "Log (and optionally push to CloudWatch) Kafka consumer lag and DLQ size."

    def add_arguments(self, parser):
        parser.add_argument("--interval", type=int, default=60)
        parser.add_argument("--lag-threshold", type=int, default=100)
        parser.add_argument("--once", action="store_true", help="print one snapshot and exit")

    def handle(self, *args, interval, lag_threshold, once, **options):
        inspector = KafkaInspector()
        namespace = os.environ.get("CLOUDWATCH_NAMESPACE")
        cloudwatch = None
        if namespace:
            import boto3

            cloudwatch = boto3.client("cloudwatch")

        stopping = False

        def stop(*_):
            nonlocal stopping
            stopping = True

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)

        previous = None
        try:
            while not stopping:
                try:
                    snapshot = inspector.snapshot()
                except Exception:
                    logger.exception("could not read Kafka metrics")
                else:
                    logger.info("kafka metrics", extra={"metric": "kafka", **snapshot})
                    for alert in evaluate(previous, snapshot, lag_threshold):
                        logger.warning(alert, extra={"alert": True})
                    if cloudwatch:
                        cloudwatch.put_metric_data(Namespace=namespace, MetricData=to_metric_data(snapshot))
                    previous = snapshot
                    if once:
                        self.stdout.write(str(snapshot))
                        return
                for _ in range(interval):
                    if stopping:
                        break
                    time.sleep(1)
        finally:
            inspector.close()


def to_metric_data(snapshot):
    data = [
        {"MetricName": "ConsumerLag", "Dimensions": [{"Name": "ConsumerGroup", "Value": group}], "Value": lag}
        for group, lag in snapshot["lag"].items()
    ]
    data.append({"MetricName": "DeadLetterMessages", "Value": snapshot["dlq_messages"]})
    return data
