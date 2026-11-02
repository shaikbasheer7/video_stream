import random
from datetime import UTC, datetime

import pandas as pd

from pipeline.aggregate import aggregate_day
from pipeline.seed_demo import session_events

VIDEO = "aaaaaaaa-0000-0000-0000-000000000000"


def test_demo_events_run_through_the_real_aggregation_with_a_declining_curve():
    rng = random.Random(1)
    start = datetime(2026, 11, 1, 10, tzinfo=UTC)
    events = [row for _ in range(300) for row in session_events(rng, VIDEO, 120.0, start)]
    agg = aggregate_day(pd.DataFrame(events), {VIDEO: 120.0})

    stats = agg.video_stats.iloc[0]
    assert stats["views"] == 300
    assert 0 < stats["avg_completion_pct"] < 100
    curve = agg.retention.sort_values("position_pct")["viewers"].tolist()
    assert curve[0] > curve[-1] > 0  # viewers drop off, but some finish
    assert curve[0] > 0.8 * stats["views"]  # nearly everyone watched the opening
    assert curve == sorted(curve, reverse=True)  # nobody joins halfway in this data
    assert set(agg.quality["quality"]) <= {"480p", "720p", "1080p"}
