"""Daily analytics: yesterday's playback events (MongoDB) -> aggregate tables (PostgreSQL) -> Superset, then
trending lists, similar videos and personal picks for the API.

Trigger with config {"date": "YYYY-MM-DD"} to recompute one day; re-running replaces that day.
"""

import logging
from datetime import UTC, date, datetime, timedelta

from airflow.sdk import dag, get_current_context, task

logger = logging.getLogger(__name__)


def target_day():
    """The day to process: the "date" run config if given, else the day before this run."""
    context = get_current_context()
    requested = (context["dag_run"].conf or {}).get("date")
    if requested:
        return date.fromisoformat(requested)
    return context["logical_date"].astimezone(UTC).date() - timedelta(days=1)


@dag(
    dag_id="daily_video_pipeline",
    schedule="0 2 * * *",  # 02:00 UTC, once yesterday's late flushes have arrived
    start_date=datetime(2026, 1, 1, tzinfo=UTC),
    catchup=False,  # backfill deliberately (python -m pipeline.run --from ... --to ...)
    max_active_runs=1,
    default_args={"retries": 2, "retry_delay": timedelta(minutes=5)},
    doc_md=__doc__,
    tags=["analytics"],
)
def daily_video_pipeline():
    @task
    def check_new_events():
        """Fails fast if MongoDB is unreachable. Zero events is logged, not an error: a quiet day is valid."""
        from pipeline import io

        day = target_day()
        count = io.count_events(day)
        logger.info("%s: %d raw events", day, count)
        return count

    @task
    def aggregate_and_load_stats():
        """pandas aggregation, then one Postgres transaction replacing the day."""
        from pipeline.run import aggregate_and_load

        return aggregate_and_load(target_day())

    @task(retries=0)  # bad numbers won't fix themselves by retrying
    def data_quality_checks():
        from pipeline.quality import check_day

        return check_day(target_day())

    @task
    def refresh_trending():
        """SQL over the daily stats: trending (recent views) and popular (watch time)."""
        from pipeline.publish import refresh_ranked_lists

        return refresh_ranked_lists(target_day())

    @task
    def embed_videos():
        """Only new or edited videos are embedded."""
        from pipeline.publish import refresh_embeddings

        return refresh_embeddings()

    @task
    def publish_similar_videos():
        from pipeline.publish import publish_similar_videos as publish

        return publish()

    @task
    def publish_recommendations():
        """Top picks per user from their watch history; replaced in one transaction."""
        from pipeline.publish import publish_recommendations as publish

        return publish()

    # Recommendations build on the stats, so a failed quality check stops them: yesterday's lists stay up.
    (
        check_new_events()
        >> aggregate_and_load_stats()
        >> data_quality_checks()
        >> refresh_trending()
        >> embed_videos()
        >> publish_similar_videos()
        >> publish_recommendations()
    )


daily_video_pipeline()
