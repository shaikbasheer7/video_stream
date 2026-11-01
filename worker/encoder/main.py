"""Encoding worker: consumes video.uploaded, writes HLS to S3, publishes video.ready / video.failed.

Delivery is at-least-once: the offset is committed only after a message is fully handled
(ready or failed published). A crash mid-encode means the message is redelivered and redone.
"""

import json
import logging
import signal
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath

from confluent_kafka import Consumer, KafkaException, TopicPartition

from . import config, messaging, pipeline, storage
from .db import Database
from .errors import InvalidSource

logger = logging.getLogger("encoder")

GENERIC_FAILURE = "Encoding failed. Try uploading the video again."


class EncodeJob:
    """Handles one video.uploaded event. Collaborators are injectable for tests."""

    def __init__(self, db, storage=storage, encode=pipeline.encode, publish=messaging.publish, sleep=time.sleep):
        self.db = db
        self.storage = storage
        self.encode = encode
        self.publish = publish
        self.sleep = sleep

    def handle(self, event):
        video_id = event["video_id"]
        source_key = self.db.claim(video_id, event.get("event_id", ""))
        if source_key is None:
            logger.info("video %s: duplicate, already done, or deleted; skipping", video_id)
            return

        error, attempt = None, 0
        for attempt in range(1, config.MAX_ATTEMPTS + 1):
            try:
                self.process(video_id, source_key)
                return
            except InvalidSource as exc:
                error = exc
                logger.warning("video %s: invalid source: %s", video_id, exc)
                break
            except Exception as exc:
                error = exc
                logger.exception("video %s: attempt %d/%d failed", video_id, attempt, config.MAX_ATTEMPTS)
                if attempt < config.MAX_ATTEMPTS:
                    self.sleep(config.RETRY_BACKOFF_SEC * 3 ** (attempt - 1))

        self.fail(event, error, attempt)

    def process(self, video_id, source_key):
        hls_prefix = f"hls/{video_id}/"
        thumbnail_key = f"thumbnails/{video_id}/default.jpg"
        with tempfile.TemporaryDirectory(prefix=f"encode-{video_id}-") as tmp:  # removed in every case
            source = Path(tmp) / f"source{PurePosixPath(source_key).suffix}"
            self.storage.download(source_key, source)
            result = self.encode(source, Path(tmp) / "out", config.MAX_DURATION_SEC)
            count = self.storage.upload_dir(result.hls_dir, hls_prefix)
            self.storage.upload_file(result.thumbnail, thumbnail_key)

        # The owner may have deleted the video while it was encoding.
        if not self.db.exists(video_id):
            logger.info("video %s: deleted during encoding, removing outputs", video_id)
            self.storage.delete_prefix(hls_prefix)
            self.storage.delete_prefix(f"thumbnails/{video_id}/")
            return

        source = result.source
        self.publish(
            messaging.VIDEO_READY,
            video_id,
            {
                "video_id": video_id,
                "master_key": f"{hls_prefix}master.m3u8",
                "qualities": [v.quality for v in result.variants],
                "renditions": [
                    {
                        "quality": v.quality,
                        "playlist_key": f"{hls_prefix}{v.quality}/index.m3u8",
                        "width": v.width,
                        "height": v.height,
                        "bitrate_kbps": v.bitrate_kbps,
                    }
                    for v in result.variants
                ],
                "duration_sec": round(source.duration_sec, 3),
                "width": source.width,
                "height": source.height,
                "thumbnail_key": thumbnail_key,
            },
        )
        logger.info("video %s: ready (%d files, %s)", video_id, count, [v.quality for v in result.variants])

    def fail(self, event, error, attempts):
        video_id = event["video_id"]
        user_message = str(error) if isinstance(error, InvalidSource) else GENERIC_FAILURE
        self.publish(
            messaging.VIDEO_FAILED, video_id, {"video_id": video_id, "error": user_message, "attempts": attempts}
        )
        self.publish(
            messaging.VIDEO_UPLOADED_DLQ,
            video_id,
            {
                "video_id": video_id,
                "original": event,
                "error": f"{type(error).__name__}: {error}",
                "attempts": attempts,
            },
        )
        logger.error("video %s: failed after %d attempt(s), sent to DLQ", video_id, attempts)


def touch_heartbeat():
    Path(config.HEARTBEAT_FILE).touch()


def run_while_polling(consumer, fn):
    """Run fn in a thread while polling the (paused) consumer, so a long encode never exceeds
    max.poll.interval.ms and triggers a rebalance."""
    consumer.pause(consumer.assignment())
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(fn)
            while not future.done():
                touch_heartbeat()
                stray = consumer.poll(0.5)
                if stray is not None and not stray.error():
                    # A rebalance handed us a new, unpaused partition: put the message back for later.
                    tp = TopicPartition(stray.topic(), stray.partition(), stray.offset())
                    consumer.seek(tp)
                    consumer.pause([tp])
            return future.result()
    finally:
        consumer.resume(consumer.assignment())


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True
        logger.info("shutting down after the current message")

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    consumer = Consumer(
        {
            "bootstrap.servers": config.KAFKA_BOOTSTRAP_SERVERS,
            "group.id": config.GROUP_ID,
            "enable.auto.commit": False,
            "auto.offset.reset": "earliest",
        }
    )
    consumer.subscribe([messaging.VIDEO_UPLOADED])
    job = EncodeJob(Database())
    logger.info("encoder consuming %s as group %s", messaging.VIDEO_UPLOADED, config.GROUP_ID)

    try:
        while not stopping:
            touch_heartbeat()
            msg = consumer.poll(1.0)
            if msg is None:
                continue
            if msg.error():
                logger.warning("consumer error: %s", msg.error())
                continue

            try:
                event = json.loads(msg.value())
                event["video_id"]  # noqa: B018 (validate shape before doing work)
            except (ValueError, KeyError, TypeError):
                logger.error("unreadable message at %s[%d]@%d, skipping", msg.topic(), msg.partition(), msg.offset())
                consumer.commit(message=msg, asynchronous=False)
                continue

            try:
                run_while_polling(consumer, lambda event=event: job.handle(event))
            except Exception:
                # Couldn't even record the outcome (DB/Kafka down): leave uncommitted and retry the message.
                logger.exception("video %s: could not be handled, will retry", event.get("video_id"))
                consumer.seek(TopicPartition(msg.topic(), msg.partition(), msg.offset()))
                time.sleep(config.RETRY_BACKOFF_SEC)
                continue

            try:
                consumer.commit(message=msg, asynchronous=False)
            except KafkaException as exc:
                # Partition was reassigned meanwhile; the new owner redoes it (handling is idempotent).
                logger.warning("commit failed: %s", exc)
    finally:
        consumer.close()


if __name__ == "__main__":
    main()
