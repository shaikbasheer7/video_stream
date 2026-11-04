"""Kafka consumer lag and dead-letter queue size: the two metrics the blueprint asks to alert on."""

from confluent_kafka import Consumer, ConsumerGroupTopicPartitions, TopicPartition
from confluent_kafka.admin import AdminClient
from django.conf import settings

from . import kafka

# Each consumer group and the topics it reads (see common/management/commands/run_consumer.py and the encoder).
GROUPS = {
    "encoder": [kafka.VIDEO_UPLOADED],
    "api-status": [kafka.VIDEO_READY, kafka.VIDEO_FAILED],
    "analytics": [kafka.EVENTS_PLAYBACK],
    "notify": [kafka.VIDEO_READY, kafka.VIDEO_FAILED],
    "feed": [kafka.VIDEO_READY],
}
DLQ_TOPICS = [kafka.VIDEO_UPLOADED_DLQ, kafka.VIDEO_READY_ML_DLQ]
NO_OFFSET = -1001  # librdkafka OFFSET_INVALID: the group hasn't committed on this partition yet


def compute_lag(partitions, committed, watermarks):
    """partitions: [(topic, partition)], committed: {(t, p): offset}, watermarks: {(t, p): (low, high)}.

    Lag is how many messages are waiting. A partition the group has never committed on counts everything
    still retained (it will start from the earliest offset).
    """
    total = 0
    for tp in partitions:
        low, high = watermarks[tp]
        offset = committed.get(tp, NO_OFFSET)
        total += max(0, high - (offset if offset >= 0 else low))
    return total


class KafkaInspector:
    def __init__(self):
        self.admin = AdminClient(kafka.client_config())
        # Only used to read watermarks; never subscribes or commits.
        self.reader = Consumer(kafka.client_config(**{"group.id": "lag-monitor", "enable.auto.commit": False}))

    def partitions(self, topics):
        metadata = self.admin.list_topics(timeout=10)
        return [(t, p) for t in topics if t in metadata.topics for p in metadata.topics[t].partitions]

    def watermarks(self, partitions):
        return {tp: self.reader.get_watermark_offsets(TopicPartition(*tp), timeout=10) for tp in partitions}

    def committed(self, group, partitions):
        request = ConsumerGroupTopicPartitions(group, [TopicPartition(t, p) for t, p in partitions])
        result = self.admin.list_consumer_group_offsets([request])[group].result(timeout=10)
        return {(tp.topic, tp.partition): tp.offset for tp in result.topic_partitions}

    def snapshot(self):
        """{"lag": {group: messages waiting}, "dlq_messages": total in the dead-letter topics}."""
        lag = {}
        # The ML worker is optional (Compose profile `ml`): without it, its group would only ever show a growing lag.
        groups = {**GROUPS, "ml": [kafka.VIDEO_READY]} if settings.ML_WORKER_DB_PASSWORD else dict(GROUPS)
        if settings.LAKE_SINK_ENABLED:  # the same goes for Kafka Connect (Compose profile `bigdata`)
            groups["connect-lake-sink"] = [kafka.EVENTS_PLAYBACK]
        for group, topics in groups.items():
            partitions = self.partitions(topics)
            lag[group] = compute_lag(partitions, self.committed(group, partitions), self.watermarks(partitions))
        dlq_partitions = self.partitions(DLQ_TOPICS)
        dlq = sum(high - low for low, high in self.watermarks(dlq_partitions).values())
        return {"lag": lag, "dlq_messages": dlq}

    def close(self):
        self.reader.close()
