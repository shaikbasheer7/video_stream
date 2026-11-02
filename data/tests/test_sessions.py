import pytest

from pipeline.sessions import Segment, covered_seconds, retention_slices, summarize_session


def e(kind, position, quality="720p", **extra):
    return {"type": kind, "position_sec": position, "quality": quality, **extra}


def test_plain_playback_counts_the_time_between_events():
    s = summarize_session([e("play", 0), e("progress", 10), e("progress", 20), e("pause", 24)])
    assert s.played and s.watch_time_sec == 24


def test_paused_time_is_not_watching():
    s = summarize_session(
        [e("play", 0), e("pause", 5), e("seek", 5, from_sec=5, to_sec=50), e("play", 50), e("pause", 52)]
    )
    assert s.watch_time_sec == 7


def test_a_seek_ends_the_segment_at_its_origin_and_resumes_at_its_target():
    s = summarize_session([e("play", 0), e("seek", 40, from_sec=6, to_sec=40), e("pause", 43)])
    assert [(x.start, x.end) for x in s.segments] == [(0, 6), (40, 43)]


def test_seek_before_play_on_resume_counts_nothing():
    s = summarize_session([e("seek", 43, from_sec=0, to_sec=43), e("play", 43), e("progress", 53)])
    assert [(x.start, x.end) for x in s.segments] == [(43, 53)]


def test_session_continuing_from_yesterday_has_no_view_but_keeps_its_watch_time():
    s = summarize_session([e("progress", 100), e("progress", 110)])
    assert not s.played and s.watch_time_sec == 10


def test_unexplained_jump_is_not_counted():
    s = summarize_session([e("play", 0), e("progress", 500), e("progress", 510)])
    assert s.watch_time_sec == 10


def test_stall_before_any_watching_is_startup_later_ones_are_buffering():
    s = summarize_session(
        [e("play", 0), e("buffering", 0, duration_ms=400), e("progress", 10), e("buffering", 12, duration_ms=900)]
    )
    assert (s.startup_events, s.startup_ms) == (1, 400)
    assert (s.buffering_events, s.buffering_ms) == (1, 900)


def test_seconds_go_to_the_rendition_reported_when_they_ended():
    s = summarize_session(
        [
            e("play", 0, quality=None),
            e("progress", 10, "1080p"),
            e("quality_change", 14, "480p"),
            e("progress", 24, "480p"),
        ]
    )
    by_quality = {}
    for x in s.segments:
        by_quality[x.quality] = by_quality.get(x.quality, 0) + x.seconds
    assert by_quality == {"1080p": 10, "480p": 14}
    assert s.quality_changes == 1


def test_nan_fields_from_pandas_rows_are_treated_as_missing():
    s = summarize_session([e("play", 0), e("buffering", float("nan"), duration_ms=float("nan")), e("progress", 10)])
    assert s.watch_time_sec == 10 and s.startup_ms == 0


def test_complete_event():
    assert summarize_session([e("play", 90), e("complete", 95, watch_time_sec=5)]).completed


def test_rewatching_is_not_double_counted_in_coverage():
    segments = [Segment(0, 10, "q"), Segment(5, 15, "q"), Segment(0, 3, "q"), Segment(30, 40, "q")]
    assert covered_seconds(segments) == 25


@pytest.mark.parametrize(
    ("segments", "expected"),
    [
        ([Segment(0, 10, "q")], {0, 1}),  # 100 s video: 5 s slices
        ([Segment(0, 7.4, "q")], {0}),  # second slice under half watched
        ([Segment(0, 7.5, "q")], {0, 1}),  # exactly half watched
        ([Segment(95, 100, "q")], {19}),
        ([], set()),
    ],
)
def test_retention_slices(segments, expected):
    assert retention_slices(segments, 100, 20) == expected
