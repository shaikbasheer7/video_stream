"""Daily analytics: yesterday's playback events (MongoDB) -> aggregate tables (PostgreSQL) -> Superset.

Later phases extend this DAG: recommendations in Phase 8, PySpark over the S3 data lake in Phase 10.

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

    check_new_events() >> aggregate_and_load_stats() >> data_quality_checks()


daily_video_pipeline()
