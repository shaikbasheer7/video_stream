"""Data quality checks on a loaded day: the tables must agree with each other and with the raw events."""

from . import io


class DataQualityError(Exception):
    pass


def find_problems(raw_sessions, platform, video_totals, retention_over_views, bad_completion, negative_rows):
    """Pure comparison; returns a list of human-readable problems."""
    problems = []
    if platform is None:
        problems.append("no daily_platform_stats row for this day")
        return problems
    views, sessions, watch_time = platform
    if sessions != raw_sessions:
        problems.append(f"platform sessions {sessions} != {raw_sessions} distinct sessions in the raw events")
    video_views, video_watch_time = video_totals
    if views != video_views:
        problems.append(f"platform views {views} != {video_views} summed over videos")
    if abs(watch_time - video_watch_time) > 1:
        problems.append(f"platform watch time {watch_time} != {video_watch_time} summed over videos")
    if retention_over_views:
        problems.append(f"{retention_over_views} video(s) have a retention slice with more viewers than views")
    if bad_completion:
        problems.append(f"{bad_completion} row(s) have a completion outside 0-100%")
    if negative_rows:
        problems.append(f"{negative_rows} row(s) have negative watch time or buffering")
    return problems


def check_day(day):
    """Raises DataQualityError (failing the Airflow task) if anything doesn't add up. Returns a summary."""
    start, end = io.day_bounds(day)
    raw_sessions = len(
        io.mongo_collection().distinct(
            "session_id",
            {"received_at": {"$gte": start, "$lt": end}},
        )
    )
    with io.postgres() as conn:
        platform = conn.execute(
            "SELECT views, sessions, watch_time_sec FROM daily_platform_stats WHERE date = %s", (day,)
        ).fetchone()
        video_views, video_watch_time = conn.execute(
            "SELECT COALESCE(SUM(views), 0), COALESCE(SUM(watch_time_sec), 0) FROM daily_video_stats WHERE date = %s",
            (day,),
        ).fetchone()
        retention_over_views = conn.execute(
            """SELECT count(DISTINCT r.video_id) FROM daily_video_retention r
                 JOIN daily_video_stats s ON s.date = r.date AND s.video_id = r.video_id
                WHERE r.date = %s AND r.viewers > s.views""",
            (day,),
        ).fetchone()[0]
        bad_completion = conn.execute(
            """SELECT count(*) FROM daily_video_stats
                WHERE date = %s AND (avg_completion_pct < 0 OR avg_completion_pct > 100)""",
            (day,),
        ).fetchone()[0]
        negative = conn.execute(
            """SELECT count(*) FROM daily_video_stats
                WHERE date = %s AND (watch_time_sec < 0 OR buffering_ms < 0)""",
            (day,),
        ).fetchone()[0]

    problems = find_problems(
        raw_sessions, platform, (video_views, video_watch_time), retention_over_views, bad_completion, negative
    )
    if problems:
        raise DataQualityError(f"{day}: " + "; ".join(problems))
    return {"date": str(day), "raw_sessions": raw_sessions, "views": video_views}
