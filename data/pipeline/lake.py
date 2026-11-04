"""The data lake and the daily aggregation in PySpark (blueprint steps 56-57). Used when ANALYTICS_ENGINE=spark.

    Kafka Connect -> lake-landing/events.playback/date=.../*.json.gz   raw events, as they arrived
    build_partition -> lake/events/date=.../*.parquet                  typed, deduplicated, one day by receive time
    aggregate_day_spark -> the same four analytics tables as aggregate.py

Backfill what MongoDB already holds:  python -m pipeline.lake --from 2026-10-01 --to 2026-10-31
"""

import argparse
import json
import logging
import os
from datetime import date, timedelta
from functools import cache
from glob import glob

import pandas as pd
from pyspark.errors import AnalysisException
from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import (
    BooleanType,
    DoubleType,
    LongType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

from . import io
from .aggregate import RETENTION_SLICES, SLICE_PCT, DailyAggregates, in_session_order, session_detail

logger = logging.getLogger(__name__)

LANDING = "lake-landing/events.playback"
LAKE = "lake/events"
JARS = os.environ.get("SPARK_JARS_DIR", "/opt/spark-jars")
# Connect dates a file by when Kafka received the event, this by when the API did: they can differ around midnight.
MAX_EVENTS_MISSING_FROM_LAKE = 0.01

EVENT_SCHEMA = StructType(
    [
        StructField("event_id", StringType()),
        StructField("type", StringType()),
        StructField("video_id", StringType()),
        StructField("session_id", StringType()),
        StructField("user_id", LongType()),
        StructField("anonymous_id", StringType()),
        StructField("position_sec", DoubleType()),
        StructField("quality", StringType()),
        StructField("device", StringType()),
        StructField("country", StringType()),
        StructField("from_sec", DoubleType()),
        StructField("to_sec", DoubleType()),
        StructField("from_quality", StringType()),
        StructField("to_quality", StringType()),
        StructField("auto", BooleanType()),
        StructField("duration_ms", LongType()),
        StructField("watch_time_sec", DoubleType()),
        StructField("client_ts", TimestampType()),
        StructField("received_at", TimestampType()),
    ]
)
SESSION_SCHEMA = (
    "video_id string, session_id string, viewer string, played boolean, completed boolean, completion_pct double, "
    "watch_time_sec double, buffering_events long, buffering_ms long, has_duration boolean, slices array<int>, "
    "quality_rows string"
)
QUALITY_ROW_SCHEMA = (
    "array<struct<device:string,country:string,quality:string,session_id:string,watch_time_sec:double,"
    "buffering_events:long,buffering_ms:long,startup_events:long,startup_ms:long,quality_changes:long>>"
)


def bucket():
    return os.environ.get("S3_BUCKET", "streaming-media")


def s3a(path):
    return f"s3a://{bucket()}/{path}"


@cache
def spark_session():
    """One local Spark in this process. Pointing SPARK_MASTER at a cluster is what scaling out would change."""
    builder = (
        SparkSession.builder.appName("streaming-pipeline")
        .master(os.environ.get("SPARK_MASTER", "local[2]"))
        .config("spark.driver.memory", os.environ.get("SPARK_DRIVER_MEMORY", "1g"))
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.shuffle.partitions", os.environ.get("SPARK_SHUFFLE_PARTITIONS", "4"))
        .config("spark.sql.sources.partitionOverwriteMode", "dynamic")
        .config("spark.ui.enabled", "false")
        .config("spark.jars", ",".join(glob(f"{JARS}/*.jar")))
    )
    if os.environ.get("S3_ENDPOINT_URL"):
        builder = (
            builder.config("spark.hadoop.fs.s3a.endpoint", os.environ["S3_ENDPOINT_URL"])
            .config("spark.hadoop.fs.s3a.path.style.access", "true")
            .config("spark.hadoop.fs.s3a.connection.ssl.enabled", "false")
            .config("spark.hadoop.fs.s3a.endpoint.region", os.environ.get("AWS_REGION", "us-east-1"))
        )
    session = builder.getOrCreate()
    session.sparkContext.setLogLevel("WARN")
    return session


def clean_events(frame, day):
    """One day by server receive time, each event once, and no client clock ahead of the server (as analytics does)."""
    start, end = io.day_bounds(day)
    return (
        frame.where(
            F.col("event_id").isNotNull()
            & F.col("video_id").isNotNull()
            & F.col("session_id").isNotNull()
            & F.col("received_at").isNotNull()
            & (F.col("received_at") >= F.lit(start))
            & (F.col("received_at") < F.lit(end))
        )
        .dropDuplicates(["event_id"])
        .withColumn("client_ts", F.least(F.col("client_ts"), F.col("received_at")))
    )


def _read_landing(spark, day):
    days = [str(day + timedelta(days=offset)) for offset in (-1, 0, 1)]
    columns = [field.name for field in EVENT_SCHEMA.fields]
    schema = StructType([*EVENT_SCHEMA.fields, StructField("date", StringType())])
    try:
        # `date` comes from the folder names, so Spark only opens these three days.
        return spark.read.schema(schema).json(s3a(LANDING)).where(F.col("date").isin(days)).select(columns)
    except AnalysisException as exc:
        if "PATH_NOT_FOUND" in str(exc):
            return spark.createDataFrame([], EVENT_SCHEMA)
        raise


def _write_partition(frame, day):
    frame.coalesce(1).write.mode("overwrite").parquet(s3a(f"{LAKE}/date={day}"))


def _merge_into_partition(new_events, day):
    """Add events to a day and rewrite it, so a rebuild can't lose what a backfill put there. Safe to re-run."""
    merged = clean_events(read_partition(day).unionByName(new_events), day)
    # The rewrite replaces the files it reads from, so first cut the link to them.
    merged = merged.localCheckpoint(eager=True)
    count = merged.count()
    if count:
        _write_partition(merged, day)
    return count


def build_partition(day):
    """Landing files -> one day's Parquet. Returns the number of events the day now has."""
    count = _merge_into_partition(_read_landing(spark_session(), day), day)
    logger.info("%s: %d events in the lake", day, count)
    return count


def _typed(value, kind):
    """A value from pandas or MongoDB, as the type Spark's schema insists on. NaN means missing."""
    if value is None or value != value:
        return None
    if isinstance(kind, LongType):
        return int(value)
    if isinstance(kind, DoubleType):
        return float(value)
    if isinstance(kind, TimestampType):
        return value.to_pydatetime() if hasattr(value, "to_pydatetime") else value
    return value


def to_events_frame(records):
    """[dict] -> a Spark frame with EVENT_SCHEMA. Missing fields are null."""
    rows = [{f.name: _typed(record.get(f.name), f.dataType) for f in EVENT_SCHEMA.fields} for record in records]
    return spark_session().createDataFrame(rows, EVENT_SCHEMA)


def backfill_from_mongo(day):
    """Events from before Kafka Connect ran. MongoDB keeps them for EVENTS_TTL_DAYS, so do this before they expire."""
    raw = io.read_events(day)
    if raw.empty:
        return 0
    records = raw.rename(columns={"_id": "event_id"}).to_dict("records")
    count = _merge_into_partition(to_events_frame(records), day)
    logger.info("%s: backfilled from MongoDB, %d events in the lake", day, count)
    return count


def read_partition(day):
    spark = spark_session()
    try:
        return spark.read.schema(EVENT_SCHEMA).parquet(s3a(f"{LAKE}/date={day}"))
    except AnalysisException as exc:
        if "PATH_NOT_FOUND" in str(exc):
            return spark.createDataFrame([], EVENT_SCHEMA)
        raise


def lake_problems(lake_events, mongo_events, null_keys):
    """Pure comparison for the data quality check. MongoDB is written by a separate consumer, so it's a fair witness."""
    problems = []
    if null_keys:
        problems.append(f"{null_keys} lake row(s) have no event, video or session id")
    if mongo_events and lake_events < mongo_events * (1 - MAX_EVENTS_MISSING_FROM_LAKE):
        problems.append(f"the lake has {lake_events} events but MongoDB has {mongo_events}: the lake is behind")
    return problems


def check_partition(day):
    events = read_partition(day)
    keys = F.col("event_id").isNull() | F.col("video_id").isNull() | F.col("session_id").isNull()
    return lake_problems(events.count(), io.count_events(day), events.where(keys).count())


def _session_function(durations):
    def summarize(group):
        group = in_session_order(group)
        video_id, session_id = group["video_id"].iloc[0], group["session_id"].iloc[0]
        duration = durations.get(video_id)
        session, slices, quality_rows = session_detail(video_id, session_id, group, duration)
        return pd.DataFrame(
            [
                {
                    **session,
                    "has_duration": bool(duration),
                    "slices": [int(i) for i in slices],
                    "quality_rows": json.dumps(quality_rows),
                }
            ]
        )

    return summarize


def _platform(sessions, new_uploads):
    row = sessions.agg(
        F.count("*").alias("sessions"),
        F.sum(F.col("played").cast("long")).alias("views"),
        F.countDistinct(F.when(F.col("played"), F.col("viewer"))).alias("unique_viewers"),
        F.sum("watch_time_sec").alias("watch_time_sec"),
        F.countDistinct(F.when(F.col("played"), F.col("video_id"))).alias("videos_watched"),
    ).first()
    return {
        "views": int(row["views"] or 0),
        "sessions": int(row["sessions"]),
        "unique_viewers": int(row["unique_viewers"]),
        "watch_time_sec": round(float(row["watch_time_sec"] or 0), 3),
        "videos_watched": int(row["videos_watched"]),
        "new_uploads": new_uploads,
    }


def aggregate_day_spark(events, durations, new_uploads=0):
    """The same results as aggregate.aggregate_day, computed in Spark. Only the per-day tables reach the driver."""
    empty = {"views": 0, "sessions": 0, "unique_viewers": 0, "watch_time_sec": 0.0, "videos_watched": 0}
    if events.isEmpty():
        no_quality = pd.DataFrame(
            columns=["device", "country", "quality", "sessions", "watch_time_sec", "buffering_events", "buffering_ms",
                     "startup_events", "startup_ms", "quality_changes"]
        )  # fmt: skip
        return DailyAggregates(pd.DataFrame(), pd.DataFrame(), no_quality, {**empty, "new_uploads": new_uploads})

    sessions = (
        events.groupBy("video_id", "session_id").applyInPandas(_session_function(durations), SESSION_SCHEMA).cache()
    )
    video_stats = sessions.groupBy("video_id").agg(
        F.sum(F.col("played").cast("long")).alias("views"),
        F.countDistinct(F.when(F.col("played"), F.col("viewer"))).alias("unique_viewers"),
        F.round(F.sum("watch_time_sec"), 3).alias("watch_time_sec"),
        F.round(F.avg(F.when(F.col("played"), F.col("completion_pct"))), 2).alias("avg_completion_pct"),
        F.sum(F.col("completed").cast("long")).alias("completions"),
        F.sum("buffering_events").alias("buffering_events"),
        F.sum("buffering_ms").alias("buffering_ms"),
    )

    # Every slice of every viewed video, including slices nobody reached: a curve needs its zeros.
    slices = F.array([F.lit(i) for i in range(RETENTION_SLICES)])
    viewed = sessions.where(F.col("played") & F.col("has_duration")).select("video_id").distinct()
    all_slices = viewed.select("video_id", F.explode(slices).alias("slice"))
    reached = (
        sessions.select("video_id", "session_id", F.explode("slices").alias("slice"))
        .groupBy("video_id", "slice")
        .agg(F.countDistinct("session_id").alias("viewers"))
    )
    retention = all_slices.join(reached, ["video_id", "slice"], "left").select(
        "video_id",
        (F.col("slice") * SLICE_PCT).alias("position_pct"),
        F.coalesce(F.col("viewers"), F.lit(0)).alias("viewers"),
    )

    quality = (
        sessions.select(F.explode(F.from_json("quality_rows", QUALITY_ROW_SCHEMA)).alias("row"))
        .select("row.*")
        .groupBy("device", "country", "quality")
        .agg(
            F.countDistinct("session_id").alias("sessions"),
            F.round(F.sum("watch_time_sec"), 3).alias("watch_time_sec"),
            F.sum("buffering_events").alias("buffering_events"),
            F.sum("buffering_ms").alias("buffering_ms"),
            F.sum("startup_events").alias("startup_events"),
            F.sum("startup_ms").alias("startup_ms"),
            F.sum("quality_changes").alias("quality_changes"),
        )
    )
    result = DailyAggregates(
        video_stats=video_stats.toPandas(),
        retention=retention.toPandas(),
        quality=quality.toPandas(),
        platform=_platform(sessions, new_uploads),
    )
    sessions.unpersist()
    return result


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--from", dest="start", type=date.fromisoformat, required=True)
    parser.add_argument("--to", dest="end", type=date.fromisoformat, default=None)
    args = parser.parse_args()
    day, end = args.start, args.end or args.start
    while day <= end:
        backfill_from_mongo(day)
        day += timedelta(days=1)


if __name__ == "__main__":
    main()
