"""The Spark job must count exactly what the pandas job counts. Runs real local Spark, so it needs Java."""

import shutil
from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest

pytest.importorskip("pyspark")
if shutil.which("java") is None:
    pytest.skip("needs Java", allow_module_level=True)

from test_aggregate import A, B, session  # noqa: E402

from pipeline import lake  # noqa: E402
from pipeline.aggregate import aggregate_day  # noqa: E402

DAY = date(2026, 11, 1)
T0 = datetime(2026, 11, 1, 10, 0, tzinfo=UTC)
DURATIONS = {A: 100.0}


@pytest.fixture(scope="module")
def spark():
    return lake.spark_session()


def event_rows():
    sessions = [
        session(A, "s1", [("play", 0, {}), ("progress", 10, {}), ("progress", 50, {}), ("pause", 50, {})], user=7),
        session(
            A, "s2",
            [("play", 0, {})] + [("progress", p, {}) for p in range(10, 101, 10)]
            + [("complete", 100, {"watch_time_sec": 100})],
            user=7, device="mobile",
        ),
        session(
            B, "s3",
            [("play", 0, {}), ("buffering", 0, {"duration_ms": 100}), ("progress", 10, {}),
             ("buffering", 12, {"duration_ms": 800}), ("pause", 20, {})],
            anon="browser-2", country="IN",
        ),
        session(A, "s4", [("progress", 30, {}), ("progress", 40, {})], user=9),
    ]  # fmt: skip
    rows = [row for s in sessions for row in s]
    for i, row in enumerate(rows):
        row["event_id"] = f"e{i}"
        row["received_at"] = row["client_ts"] + timedelta(seconds=1)
    return rows


def as_spark(spark, rows):
    return lake.to_events_frame(rows)


def by(frame, *keys):
    return frame.sort_values(list(keys)).reset_index(drop=True)


def assert_same(left, right, keys):
    columns = [c for c in left.columns]
    pd.testing.assert_frame_equal(
        by(left[columns], *keys), by(right[columns], *keys), check_dtype=False, check_exact=False, atol=0.01
    )


def test_spark_gives_the_same_tables_as_pandas(spark):
    rows = event_rows()
    pandas_day = aggregate_day(pd.DataFrame(rows), DURATIONS, new_uploads=3)
    spark_day = lake.aggregate_day_spark(as_spark(spark, rows), DURATIONS, new_uploads=3)
    assert spark_day.platform == pandas_day.platform
    assert_same(pandas_day.video_stats, spark_day.video_stats, ["video_id"])
    assert_same(pandas_day.retention, spark_day.retention, ["video_id", "position_pct"])
    assert_same(pandas_day.quality, spark_day.quality, ["device", "country", "quality"])


def test_an_empty_day_gives_zeros(spark):
    day = lake.aggregate_day_spark(spark.createDataFrame([], lake.EVENT_SCHEMA), {}, new_uploads=2)
    assert day.video_stats.empty and day.quality.empty
    assert day.platform["views"] == 0 and day.platform["new_uploads"] == 2


def test_cleaning_keeps_one_day_removes_duplicates_and_caps_client_clocks(spark):
    base = {"type": "play", "video_id": A, "session_id": "s", "position_sec": 0.0, "client_ts": T0}
    rows = [
        {**base, "event_id": "same", "received_at": T0},
        {**base, "event_id": "same", "received_at": T0},  # Connect delivers at least once
        {**base, "event_id": "fast-clock", "received_at": T0, "client_ts": T0 + timedelta(hours=2)},
        {**base, "event_id": "next-day", "received_at": T0 + timedelta(days=1)},
        {**base, "event_id": None, "received_at": T0},
    ]
    cleaned = lake.clean_events(as_spark(spark, rows), DAY).toPandas()
    assert sorted(cleaned["event_id"]) == ["fast-clock", "same"]
    fast = cleaned[cleaned["event_id"] == "fast-clock"].iloc[0]
    assert fast["client_ts"] == fast["received_at"]


def test_values_from_pandas_become_the_types_spark_insists_on(spark):
    row = lake.to_events_frame(
        [
            {"event_id": "e", "user_id": 145.0, "position_sec": 3, "quality": float("nan"), "duration_ms": 800.0,
             "received_at": pd.Timestamp(T0), "client_ts": pd.Timestamp(T0)}
        ]
    ).first()  # fmt: skip
    assert (row["user_id"], row["position_sec"], row["quality"], row["duration_ms"]) == (145, 3.0, None, 800)


def test_merging_keeps_events_already_in_the_lake(spark, tmp_path, monkeypatch):
    monkeypatch.setattr(lake, "s3a", lambda path: str(tmp_path / path))
    base = {"type": "play", "video_id": A, "session_id": "s", "position_sec": 0.0, "client_ts": T0, "received_at": T0}
    assert lake._merge_into_partition(lake.to_events_frame([{**base, "event_id": "from-mongo"}]), DAY) == 1
    assert lake._merge_into_partition(lake.to_events_frame([{**base, "event_id": "from-landing"}]), DAY) == 2
    # Nothing new, and a delivery seen twice, must not lose or double anything.
    assert lake._merge_into_partition(lake.to_events_frame([{**base, "event_id": "from-landing"}]), DAY) == 2
    ids = sorted(r["event_id"] for r in lake.read_partition(DAY).collect())
    assert ids == ["from-landing", "from-mongo"]


@pytest.mark.parametrize(
    ("lake_events", "mongo_events", "null_keys", "expected"),
    [(100, 100, 0, 0), (100, 0, 0, 0), (99, 100, 0, 0), (50, 100, 0, 1), (100, 100, 2, 1), (0, 100, 1, 2)],
)
def test_lake_problems(lake_events, mongo_events, null_keys, expected):
    assert len(lake.lake_problems(lake_events, mongo_events, null_keys)) == expected
