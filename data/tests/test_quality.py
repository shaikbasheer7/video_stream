from pipeline.quality import find_problems


def problems(**overrides):
    args = {
        "raw_sessions": 4,
        "platform": (3, 4, 180.0),
        "video_totals": (3, 180.0),
        "retention_over_views": 0,
        "bad_completion": 0,
        "negative_rows": 0,
    }
    return find_problems(**{**args, **overrides})


def test_consistent_day_passes():
    assert problems() == []


def test_each_inconsistency_is_reported():
    assert "no daily_platform_stats" in problems(platform=None)[0]
    assert "4 distinct sessions" in problems(platform=(3, 5, 180.0))[0]
    assert "summed over videos" in problems(video_totals=(2, 180.0))[0]
    assert "watch time" in problems(video_totals=(3, 90.0))[0]
    assert "more viewers than views" in problems(retention_over_views=1)[0]
    assert "completion" in problems(bad_completion=2)[0]
    assert "negative" in problems(negative_rows=1)[0]
