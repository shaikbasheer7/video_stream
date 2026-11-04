"""Live metrics with Spark Structured Streaming (blueprint step 59): events.playback -> Redis and PostgreSQL.

Run on its own:  python -m pipeline.live

Redis holds what the API serves right now. Keys expire, so if this job stops the site shows no live data rather than
old numbers. PostgreSQL keeps one row a minute for the Superset dashboard.
"""

import logging
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import redis
from pyspark.sql import functions as F
from pyspark.sql.types import LongType, StringType, StructField, StructType, TimestampType

from . import io
from .lake import spark_session

logger = logging.getLogger(__name__)

VIEWERS_KEY = "live:viewers"  # hash: video id -> sessions active in the last minute
TRENDING_KEY = "live:trending"  # sorted set: video id -> sessions in the last hour
UPDATED_KEY = "live:updated_at"
VIEWERS_TTL_SEC = 60  # refreshed while anyone is watching: player progress events come every 10 s
TRENDING_TTL_SEC = 15 * 60
METRICS_RETENTION_DAYS = 7
HEARTBEAT = Path("/tmp/heartbeat")  # noqa: S108
SCHEMA = StructType(
    [
        StructField("type", StringType()),
        StructField("video_id", StringType()),
        StructField("session_id", StringType()),
        StructField("duration_ms", LongType()),
        StructField("received_at", TimestampType()),
    ]
)


def _utc(value):
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def current_window(rows, now):
    """rows from one micro-batch (window_start, window_end, ...): those in the newest window that has started."""
    started = [r for r in rows if _utc(r["window_start"]) <= now]
    if not started:
        return []
    newest = max(_utc(r["window_start"]) for r in started)
    return [r for r in started if _utc(r["window_start"]) == newest]


def write_viewers(client, rows, now):
    """Replace the live viewer counts in one step, so the API never reads half an update."""
    current = current_window(rows, now)
    pipe = client.pipeline(transaction=True)
    pipe.delete(VIEWERS_KEY)
    if current:
        pipe.hset(VIEWERS_KEY, mapping={r["video_id"]: int(r["sessions"]) for r in current})
        pipe.expire(VIEWERS_KEY, VIEWERS_TTL_SEC)
    pipe.set(UPDATED_KEY, now.isoformat(), ex=VIEWERS_TTL_SEC)
    pipe.execute()


def write_trending(client, rows, now):
    current = current_window(rows, now)
    pipe = client.pipeline(transaction=True)
    pipe.delete(TRENDING_KEY)
    if current:
        pipe.zadd(TRENDING_KEY, {r["video_id"]: int(r["sessions"]) for r in current})
        pipe.expire(TRENDING_KEY, TRENDING_TTL_SEC)
    pipe.execute()


def minute_rows(rows):
    """Per-video rows of one-minute windows -> one row per minute for the whole platform."""
    minutes = {}
    for r in rows:
        minute = _utc(r["window_start"]).replace(second=0, microsecond=0)
        total = minutes.setdefault(minute, {"active_viewers": 0, "plays": 0, "stalls": 0})
        total["active_viewers"] += int(r["sessions"])
        total["plays"] += int(r["plays"] or 0)
        total["stalls"] += int(r["stalls"] or 0)
    return minutes


def write_minutes(rows, now):
    minutes = minute_rows(rows)
    if not minutes:
        return
    with io.postgres() as conn, conn.cursor() as cur:
        # This batch's numbers for a minute are complete for that window, so they replace any earlier ones.
        cur.execute("DELETE FROM live_metrics WHERE minute = ANY(%s)", (list(minutes),))
        cur.executemany(
            "INSERT INTO live_metrics (minute, active_viewers, plays, stalls) VALUES (%s, %s, %s, %s)",
            [(m, v["active_viewers"], v["plays"], v["stalls"]) for m, v in minutes.items()],
        )
        cur.execute("DELETE FROM live_metrics WHERE minute < %s", (now - timedelta(days=METRICS_RETENTION_DAYS),))


def _events(spark):
    kafka = (
        spark.readStream.format("kafka")
        .option("kafka.bootstrap.servers", os.environ["KAFKA_BOOTSTRAP_SERVERS"])
        .option("subscribe", "events.playback")
        .option("startingOffsets", "latest")
        .option("failOnDataLoss", "false")
        .load()
    )
    parsed = kafka.select(F.from_json(F.col("value").cast("string"), SCHEMA).alias("e")).select("e.*")
    return parsed.where(F.col("video_id").isNotNull() & F.col("received_at").isNotNull())


def _windowed(events, length, slide):
    return (
        events.withWatermark("received_at", "2 minutes")
        .groupBy(F.window("received_at", length, slide), "video_id")
        .agg(
            F.approx_count_distinct("session_id").alias("sessions"),
            F.sum(F.when(F.col("type") == "play", 1).otherwise(0)).alias("plays"),
            F.sum(F.when(F.col("type") == "buffering", 1).otherwise(0)).alias("stalls"),
        )
        .select(
            F.col("window.start").alias("window_start"),
            F.col("window.end").alias("window_end"),
            "video_id",
            "sessions",
            "plays",
            "stalls",
        )
    )


def _on_batch(handler):
    def run(batch, _batch_id):
        HEARTBEAT.touch()
        now = datetime.now(UTC)
        try:
            handler([row.asDict() for row in batch.collect()], now)
        except (redis.RedisError, OSError) as exc:  # the stream must outlive a Redis or database restart
            logger.warning("could not store live metrics: %s", exc)

    return run


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("py4j").setLevel(logging.WARNING)  # otherwise a line for every call into Java
    HEARTBEAT.touch()
    spark = spark_session()
    client = redis.Redis.from_url(os.environ["REDIS_URL"], socket_timeout=5, decode_responses=True)
    checkpoints = os.environ.get("SPARK_CHECKPOINT_DIR", "/opt/spark-checkpoints")
    events = _events(spark)
    trigger = os.environ.get("LIVE_TRIGGER", "15 seconds")

    def viewers(rows, now):
        write_viewers(client, rows, now)
        write_minutes(rows, now)

    streams = [
        _windowed(events, "1 minute", "1 minute")
        .writeStream.outputMode("update")
        .foreachBatch(_on_batch(viewers))
        .option("checkpointLocation", f"{checkpoints}/viewers")
        .trigger(processingTime=trigger)
        .start(),
        _windowed(events, "1 hour", "5 minutes")
        .writeStream.outputMode("update")
        .foreachBatch(_on_batch(lambda rows, now: write_trending(client, rows, now)))
        .option("checkpointLocation", f"{checkpoints}/trending")
        .trigger(processingTime=trigger)
        .start(),
    ]
    logger.info("live metrics running")
    while all(stream.isActive for stream in streams):
        HEARTBEAT.touch()
        time.sleep(5)
    for stream in streams:
        if stream.exception():
            raise RuntimeError(str(stream.exception()))


if __name__ == "__main__":
    main()
