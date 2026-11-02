"""One day of raw playback events -> the four analytics tables (pandas). No I/O here."""

from dataclasses import dataclass

import pandas as pd

from .sessions import covered_seconds, retention_slices, summarize_session

RETENTION_SLICES = 20
SLICE_PCT = 100 // RETENTION_SLICES


@dataclass
class DailyAggregates:
    video_stats: pd.DataFrame
    retention: pd.DataFrame
    quality: pd.DataFrame
    platform: dict


def _viewer_id(group):
    """The same person across a session: their account if any event was logged in, else the browser's id."""
    users = group["user_id"].dropna() if "user_id" in group else []
    if len(users):
        return f"user:{int(users.iloc[0])}"
    return f"anon:{group['anonymous_id'].iloc[0]}"


def _first_or_unknown(group, column):
    values = group[column].dropna() if column in group else []
    return str(values.iloc[0]) if len(values) else "unknown"


def _build_sessions(events, durations):
    rows, retention_rows, quality_rows = [], [], []
    for (video_id, session_id), group in events.sort_values("client_ts").groupby(
        ["video_id", "session_id"], sort=False
    ):
        summary = summarize_session(group.to_dict("records"))
        duration = durations.get(video_id)
        completion = None
        if summary.played and duration:
            completion = min(100.0, covered_seconds(summary.segments) / duration * 100)
            for index in retention_slices(summary.segments, duration, RETENTION_SLICES):
                retention_rows.append(
                    {"video_id": video_id, "position_pct": index * SLICE_PCT, "session_id": session_id}
                )

        rows.append(
            {
                "video_id": video_id,
                "session_id": session_id,
                "viewer": _viewer_id(group),
                "played": summary.played,
                "completed": summary.completed,
                "completion_pct": completion,
                "watch_time_sec": summary.watch_time_sec,
                "buffering_events": summary.buffering_events,
                "buffering_ms": summary.buffering_ms,
            }
        )

        # Quality view: seconds go to the rendition that played them; a session's stalls and switches go to the
        # rendition it mostly watched (or its last known one if it watched nothing).
        device, country = _first_or_unknown(group, "device"), _first_or_unknown(group, "country")
        seconds_by_quality = {}
        for segment in summary.segments:
            seconds_by_quality[segment.quality] = seconds_by_quality.get(segment.quality, 0.0) + segment.seconds
        main = max(seconds_by_quality, key=seconds_by_quality.get) if seconds_by_quality else _last_quality(group)
        for quality in set(seconds_by_quality) | {main}:
            is_main = quality == main
            quality_rows.append(
                {
                    "device": device,
                    "country": country,
                    "quality": quality,
                    "session_id": session_id,
                    "watch_time_sec": seconds_by_quality.get(quality, 0.0),
                    "buffering_events": summary.buffering_events if is_main else 0,
                    "buffering_ms": summary.buffering_ms if is_main else 0,
                    "startup_events": summary.startup_events if is_main else 0,
                    "startup_ms": summary.startup_ms if is_main else 0,
                    "quality_changes": summary.quality_changes if is_main else 0,
                }
            )
    return pd.DataFrame(rows), pd.DataFrame(retention_rows), pd.DataFrame(quality_rows)


def _last_quality(group):
    values = group["quality"].dropna() if "quality" in group else []
    return str(values.iloc[-1]) if len(values) else "unknown"


def _video_stats(sessions):
    rows = []
    for video_id, group in sessions.groupby("video_id"):
        views = group[group["played"]]
        completion = views["completion_pct"].dropna()
        rows.append(
            {
                "video_id": video_id,
                "views": len(views),
                "unique_viewers": views["viewer"].nunique(),
                "watch_time_sec": round(float(group["watch_time_sec"].sum()), 3),
                "avg_completion_pct": round(float(completion.mean()), 2) if len(completion) else None,
                "completions": int(group["completed"].sum()),
                "buffering_events": int(group["buffering_events"].sum()),
                "buffering_ms": int(group["buffering_ms"].sum()),
            }
        )
    return pd.DataFrame(rows)


def _retention(slice_rows, sessions, durations):
    """Every slice of every viewed video, including slices nobody reached: a curve needs its zeros."""
    videos = [v for v in sessions[sessions["played"]]["video_id"].unique() if durations.get(v)]
    counts = {}
    if not slice_rows.empty:
        counts = slice_rows.groupby(["video_id", "position_pct"])["session_id"].nunique().to_dict()
    rows = [
        {"video_id": v, "position_pct": i * SLICE_PCT, "viewers": counts.get((v, i * SLICE_PCT), 0)}
        for v in videos
        for i in range(RETENTION_SLICES)
    ]
    return pd.DataFrame(rows, columns=["video_id", "position_pct", "viewers"])


def _quality(quality_rows):
    columns = ["device", "country", "quality", "sessions", "watch_time_sec", "buffering_events", "buffering_ms",
               "startup_events", "startup_ms", "quality_changes"]  # fmt: skip
    if quality_rows.empty:
        return pd.DataFrame(columns=columns)
    grouped = quality_rows.groupby(["device", "country", "quality"], as_index=False).agg(
        sessions=("session_id", "nunique"),
        watch_time_sec=("watch_time_sec", "sum"),
        buffering_events=("buffering_events", "sum"),
        buffering_ms=("buffering_ms", "sum"),
        startup_events=("startup_events", "sum"),
        startup_ms=("startup_ms", "sum"),
        quality_changes=("quality_changes", "sum"),
    )
    grouped["watch_time_sec"] = grouped["watch_time_sec"].round(3)
    return grouped[columns]


def aggregate_day(events, durations, new_uploads=0):
    """events: DataFrame of raw playback_events. durations: {video_id: seconds} for videos that still exist."""
    empty_platform = {"views": 0, "sessions": 0, "unique_viewers": 0, "watch_time_sec": 0.0, "videos_watched": 0}
    if events.empty:
        return DailyAggregates(
            video_stats=pd.DataFrame(),
            retention=pd.DataFrame(),
            quality=_quality(pd.DataFrame()),
            platform={**empty_platform, "new_uploads": new_uploads},
        )

    sessions, slice_rows, quality_rows = _build_sessions(events, durations)
    viewed = sessions[sessions["played"]]
    return DailyAggregates(
        video_stats=_video_stats(sessions),
        retention=_retention(slice_rows, sessions, durations),
        quality=_quality(quality_rows),
        platform={
            "views": len(viewed),
            "sessions": len(sessions),
            "unique_viewers": viewed["viewer"].nunique(),
            "watch_time_sec": round(float(sessions["watch_time_sec"].sum()), 3),
            "videos_watched": viewed["video_id"].nunique(),
            "new_uploads": new_uploads,
        },
    )
