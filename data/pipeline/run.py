"""Run the pipeline without Airflow, e.g. to backfill:  python -m pipeline.run --from 2026-10-01 --to 2026-10-31"""

import argparse
import logging
from datetime import UTC, date, datetime, timedelta

from . import io, quality
from .aggregate import aggregate_day

logger = logging.getLogger(__name__)


def aggregate_and_load(day):
    durations, uploads = io.read_video_metadata(day)
    agg = aggregate_day(io.read_events(day), durations, new_uploads=uploads)
    io.load_day(day, agg)
    logger.info("%s: %s", day, agg.platform)
    return agg.platform


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    yesterday = datetime.now(UTC).date() - timedelta(days=1)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="start", type=date.fromisoformat, default=yesterday)
    parser.add_argument("--to", dest="end", type=date.fromisoformat, default=None)
    args = parser.parse_args()

    day, end = args.start, args.end or args.start
    while day <= end:
        aggregate_and_load(day)
        quality.check_day(day)
        day += timedelta(days=1)


if __name__ == "__main__":
    main()
