from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from pipeline.aggregate import aggregate_day

T0 = datetime(2026, 11, 1, 10, 0, tzinfo=UTC)
A, B = "aaaaaaaa-0000-0000-0000-000000000000", "bbbbbbbb-0000-0000-0000-000000000000"


def session(video, session_id, events, user=None, anon="browser-1", device="desktop", country=None):
    rows = []
    for i, (kind, position, extra) in enumerate(events):
        rows.append(
            {"video_id": video, "session_id": session_id, "type": kind, "position_sec": position, "quality": "720p",
             "user_id": user, "anonymous_id": anon, "device": device, "country": country,
             "client_ts": T0 + timedelta(seconds=i), **extra}
        )  # fmt: skip
    return rows


def frame(*sessions):
    return pd.DataFrame([row for s in sessions for row in s])


@pytest.fixture
def day():
    return aggregate_day(
        frame(
            # Same logged-in person twice: 2 views, 1 unique viewer. Half of the 100 s video, then all of it.
            session(A, "s1", [("play", 0, {}), ("progress", 10, {}), ("progress", 50, {}), ("pause", 50, {})], user=7),
            session(
                A,
                "s2",
                [("play", 0, {})]
                + [("progress", p, {}) for p in range(10, 101, 10)]
                + [("complete", 100, {"watch_time_sec": 100})],
                user=7,
                device="mobile",
            ),  # fmt: skip
            # Anonymous viewer of a second, deleted video (no known duration).
            session(
                B,
                "s3",
                [
                    ("play", 0, {}),
                    ("buffering", 0, {"duration_ms": 100}),
                    ("progress", 10, {}),
                    ("buffering", 12, {"duration_ms": 800}),
                    ("pause", 20, {}),
                ],
                anon="browser-2",
                country="IN",
            ),  # fmt: skip
            # Yesterday's session running past midnight: watch time but no new view.
            session(A, "s4", [("progress", 30, {}), ("progress", 40, {})], user=9),
        ),
        durations={A: 100.0},
        new_uploads=3,
    )


def row(df, video):
    return df[df["video_id"] == video].iloc[0]


def test_video_stats(day):
    a = row(day.video_stats, A)
    assert (a["views"], a["unique_viewers"], a["completions"]) == (2, 1, 1)
    assert a["watch_time_sec"] == 50 + 100 + 10
    assert a["avg_completion_pct"] == 75  # (50 + 100) / 2


def test_deleted_video_keeps_counts_but_has_no_completion_or_retention(day):
    b = row(day.video_stats, B)
    assert b["views"] == 1 and pd.isna(b["avg_completion_pct"])
    assert b["buffering_events"] == 1 and b["buffering_ms"] == 800  # the first stall was startup
    assert B not in set(day.retention["video_id"])


def test_retention_curve_has_all_slices_and_drops_off(day):
    curve = day.retention[day.retention["video_id"] == A].sort_values("position_pct")
    assert list(curve["position_pct"]) == list(range(0, 100, 5))
    viewers = dict(zip(curve["position_pct"], curve["viewers"], strict=True))
    assert viewers[0] == 2 and viewers[45] == 2  # both watched the first half
    assert viewers[50] == 1 and viewers[95] == 1  # only one stayed


def test_quality_table_groups_by_device_country_and_rendition(day):
    q = day.quality.set_index(["device", "country", "quality"])
    assert q.loc[("desktop", "unknown", "720p"), "sessions"] == 2  # s1 + s4
    assert q.loc[("mobile", "unknown", "720p"), "watch_time_sec"] == 100
    india = q.loc[("desktop", "IN", "720p")]
    assert (india["buffering_events"], india["startup_events"], india["startup_ms"]) == (1, 1, 100)


def test_platform_counts_unique_viewers_across_videos(day):
    assert day.platform == {
        "views": 3,
        "sessions": 4,
        "unique_viewers": 2,  # user 7 and browser-2; user 9 didn't start a view today
        "watch_time_sec": 180.0,
        "videos_watched": 2,
        "new_uploads": 3,
    }


def test_a_session_is_attributed_to_the_account_even_if_some_events_were_anonymous():
    rows = session(A, "s1", [("play", 0, {}), ("progress", 10, {})], user=None, anon="browser-1")
    rows[0]["user_id"] = 7
    other = session(A, "s2", [("play", 0, {})], user=7, anon="browser-9")
    assert row(aggregate_day(frame(rows, other), {A: 100.0}).video_stats, A)["unique_viewers"] == 1


def test_empty_day_is_all_zeros_with_uploads():
    day = aggregate_day(pd.DataFrame(), {}, new_uploads=2)
    assert day.video_stats.empty and day.retention.empty and day.quality.empty
    assert day.platform["views"] == 0 and day.platform["new_uploads"] == 2
