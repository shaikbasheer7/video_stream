import uuid

import pytest
import redis
from rest_framework.test import APIClient

from accounts.models import User
from live import metrics
from videos.models import Video


class FakePipeline:
    def __init__(self, results=None, error=None):
        self.results, self.error = results, error

    def get(self, key):
        pass

    def hgetall(self, key):
        pass

    def zrevrange(self, key, start, stop):
        pass

    def execute(self):
        if self.error:
            raise self.error
        return self.results


def serve(monkeypatch, settings, results=None, error=None):
    settings.REDIS_URL = "redis://test"
    monkeypatch.setattr(metrics, "_retry_at", 0.0)

    class Client:
        def pipeline(self, transaction):
            return FakePipeline(results, error)

    monkeypatch.setattr(metrics, "client", Client)


def make_video(status=Video.Status.READY):
    owner, _ = User.objects.get_or_create(email="owner@example.com")
    return Video.objects.create(
        owner=owner, title="Clip", original_filename="v.mp4", content_type="video/mp4", size_bytes=1,
        source_key="raw/v", status=status,
    )  # fmt: skip


@pytest.mark.django_db
def test_overview_adds_up_viewers_and_lists_trending_in_order(monkeypatch, settings):
    first, second = make_video(), make_video()
    gone = str(uuid.uuid4())
    serve(monkeypatch, settings, ["2026-11-04T10:00:00+00:00", {str(first.id): "3", str(second.id): "2"},
                                  [str(second.id), gone, "not-a-uuid", str(first.id)]])  # fmt: skip
    data = APIClient().get("/api/live/").data
    assert data["available"] is True and data["viewers_now"] == 5
    assert [v["id"] for v in data["trending"]] == [str(second.id), str(first.id)]  # deleted video dropped


@pytest.mark.django_db
def test_a_video_that_stopped_being_ready_is_not_trending(monkeypatch, settings):
    hidden = make_video(status=Video.Status.PROCESSING)
    serve(monkeypatch, settings, ["now", {}, [str(hidden.id)]])
    assert APIClient().get("/api/live/").data["trending"] == []


@pytest.mark.django_db
def test_redis_being_down_is_not_an_error(monkeypatch, settings):
    serve(monkeypatch, settings, error=redis.ConnectionError("down"))
    response = APIClient().get("/api/live/")
    assert response.status_code == 200
    assert response.data == {"available": False, "viewers_now": 0, "trending": []}


@pytest.mark.django_db
def test_after_a_failure_redis_is_left_alone_for_a_while(monkeypatch, settings):
    serve(monkeypatch, settings, error=redis.ConnectionError("down"))
    assert APIClient().get("/api/live/").data["available"] is False

    def must_not_be_called(self=None):
        raise AssertionError("tried Redis again straight after it failed")

    monkeypatch.setattr(metrics, "client", must_not_be_called)
    assert APIClient().get("/api/live/").data["available"] is False


@pytest.mark.django_db
def test_no_redis_configured_means_no_live_data(settings):
    settings.REDIS_URL = ""
    assert APIClient().get("/api/live/").data["available"] is False


@pytest.mark.django_db
def test_expired_data_counts_as_no_live_data(monkeypatch, settings):
    serve(monkeypatch, settings, [None, {}, []])
    assert APIClient().get("/api/live/").data["available"] is False


@pytest.mark.django_db
def test_viewers_of_one_video(monkeypatch, settings):
    video = make_video()
    serve(monkeypatch, settings, ["now", {str(video.id): "4"}, []])
    assert APIClient().get(f"/api/videos/{video.id}/live/").data == {"available": True, "viewers": 4}


@pytest.mark.django_db
def test_a_quiet_video_has_zero_viewers_and_an_unready_one_is_hidden(monkeypatch, settings):
    video, hidden = make_video(), make_video(status=Video.Status.PROCESSING)
    serve(monkeypatch, settings, ["now", {}, []])
    assert APIClient().get(f"/api/videos/{video.id}/live/").data["viewers"] == 0
    assert APIClient().get(f"/api/videos/{hidden.id}/live/").status_code == 404
