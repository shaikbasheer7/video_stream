"""Reads raw events from MongoDB and video metadata from PostgreSQL; writes the analytics tables."""

import os
from datetime import UTC, datetime, time, timedelta

import pandas as pd
import psycopg
from pymongo import MongoClient


def uses_spark():
    """pandas from MongoDB is the default; spark reads the data lake (Compose profile `bigdata`)."""
    return os.environ.get("ANALYTICS_ENGINE", "pandas") == "spark"


def mongo_collection():
    client = MongoClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=10_000, tz_aware=True)
    return client[os.environ.get("MONGO_DB", "streaming")].playback_events


def postgres():
    return psycopg.connect(os.environ["ANALYTICS_DB_URL"], connect_timeout=10)


def day_bounds(day):
    start = datetime.combine(day, time.min, tzinfo=UTC)
    return start, start + timedelta(days=1)


def count_events(day):
    start, end = day_bounds(day)
    return mongo_collection().count_documents({"received_at": {"$gte": start, "$lt": end}})


def read_events(day):
    """A day is by server receive time: it's indexed, and a finished day can't change (client clocks drift)."""
    start, end = day_bounds(day)
    return pd.DataFrame(list(mongo_collection().find({"received_at": {"$gte": start, "$lt": end}})))


def read_video_metadata(day):
    """({video_id: duration_sec}, number of videos created that day)."""
    start, end = day_bounds(day)
    with postgres() as conn:
        rows = conn.execute("SELECT id::text, duration_sec FROM videos_video WHERE duration_sec > 0").fetchall()
        uploads = conn.execute(
            "SELECT count(*) FROM videos_video WHERE created_at >= %s AND created_at < %s", (start, end)
        ).fetchone()[0]
    return dict(rows), uploads


def _none_if_nan(value):
    return None if pd.isna(value) else value


def load_day(day, agg):
    """Replace the day atomically, so a re-run or backfill can never double-count or leave half a day."""
    with postgres() as conn, conn.cursor() as cur:
        for table in ("daily_video_stats", "daily_video_retention", "daily_streaming_quality", "daily_platform_stats"):
            cur.execute(f"DELETE FROM {table} WHERE date = %s", (day,))  # noqa: S608 (fixed table names)

        if not agg.video_stats.empty:
            cur.executemany(
                """INSERT INTO daily_video_stats (date, video_id, views, unique_viewers, watch_time_sec,
                       avg_completion_pct, completions, buffering_events, buffering_ms)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                [
                    (day, r.video_id, int(r.views), int(r.unique_viewers), float(r.watch_time_sec),
                     _none_if_nan(r.avg_completion_pct), int(r.completions), int(r.buffering_events),
                     int(r.buffering_ms))
                    for r in agg.video_stats.itertuples()
                ],
            )  # fmt: skip
        if not agg.retention.empty:
            cur.executemany(
                "INSERT INTO daily_video_retention (date, video_id, position_pct, viewers) VALUES (%s, %s, %s, %s)",
                [(day, r.video_id, int(r.position_pct), int(r.viewers)) for r in agg.retention.itertuples()],
            )
        if not agg.quality.empty:
            cur.executemany(
                """INSERT INTO daily_streaming_quality (date, device, country, quality, sessions, watch_time_sec,
                       buffering_events, buffering_ms, startup_events, startup_ms, quality_changes)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                [
                    (day, r.device, r.country, r.quality, int(r.sessions), float(r.watch_time_sec),
                     int(r.buffering_events), int(r.buffering_ms), int(r.startup_events), int(r.startup_ms),
                     int(r.quality_changes))
                    for r in agg.quality.itertuples()
                ],
            )  # fmt: skip
        p = agg.platform
        cur.execute(
            """INSERT INTO daily_platform_stats (date, views, sessions, unique_viewers, watch_time_sec,
                   videos_watched, new_uploads) VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (day, p["views"], p["sessions"], p["unique_viewers"], p["watch_time_sec"], p["videos_watched"],
             p["new_uploads"]),
        )  # fmt: skip
