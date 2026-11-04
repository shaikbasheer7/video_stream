import json
import urllib.error
from datetime import UTC, datetime, timedelta

import pytest

from pipeline import alerts

live = pytest.importorskip("pipeline.live")
NOW = datetime(2026, 11, 4, 10, 5, 30, tzinfo=UTC)


def row(minute, video="v1", sessions=2, plays=1, stalls=0):
    start = NOW.replace(minute=minute, second=0)
    return {"window_start": start, "window_end": start + timedelta(minutes=1), "video_id": video,
            "sessions": sessions, "plays": plays, "stalls": stalls}  # fmt: skip


def test_current_window_is_the_newest_that_has_started():
    rows = [row(4, "old"), row(5, "a"), row(5, "b"), row(6, "future")]
    assert [r["video_id"] for r in live.current_window(rows, NOW)] == ["a", "b"]


def test_current_window_of_nothing():
    assert live.current_window([], NOW) == []


def test_spark_timestamps_without_a_zone_are_treated_as_utc():
    naive = {**row(5), "window_start": datetime(2026, 11, 4, 10, 5)}
    assert live.current_window([naive], NOW) == [naive]


def test_minute_rows_add_up_across_videos_and_handle_missing_counts():
    minutes = live.minute_rows([row(5, "a", 2, 1, 0), row(5, "b", 3, None, 2), row(4, "a", 1, 1, 0)])
    assert minutes[NOW.replace(minute=5, second=0)] == {"active_viewers": 5, "plays": 1, "stalls": 2}
    assert len(minutes) == 2


def test_alert_goes_to_the_webhook():
    sent = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    def opener(request, timeout):
        sent.append(json.loads(request.data))
        return Response()

    assert alerts.send("broken", url="https://hooks.example.com/x", opener=opener) is True
    assert sent[0]["text"] == "broken"


def test_no_webhook_still_logs_and_does_not_fail(caplog):
    assert alerts.send("broken", url="") is False
    assert "broken" in caplog.text


def test_undeliverable_alert_does_not_raise(caplog):
    def opener(request, timeout):
        raise urllib.error.URLError("down")

    assert alerts.send("broken", url="https://hooks.example.com/x", opener=opener) is False
    assert "could not deliver" in caplog.text
