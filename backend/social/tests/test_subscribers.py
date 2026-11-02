"""Notification + feed subscribers and the follow / feed / notification APIs."""

import uuid

import pytest
from rest_framework.test import APIClient

from accounts.models import User
from common import kafka
from notifications.handlers import handle_video_event
from social.feed import handle_video_ready
from videos.models import Video


@pytest.fixture
def users():
    make = User.objects.create_user
    return (
        make(email="creator@example.com", password="pw-123456789", display_name="Creator"),
        make(email="fan1@example.com", password="pw-123456789"),
        make(email="fan2@example.com", password="pw-123456789"),
    )


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def video_for(owner, status=Video.Status.READY):
    return Video.objects.create(
        owner=owner, title="New upload", original_filename="n.mp4", content_type="video/mp4", size_bytes=1,
        source_key="raw/n", status=status,
    )  # fmt: skip


def ready(video):
    return kafka.build_event(kafka.VIDEO_READY, {"video_id": str(video.id)})


@pytest.mark.django_db
def test_follow_unfollow_and_rules(users):
    creator, fan, _ = users
    api = client_for(fan)
    assert api.post(f"/api/users/{creator.id}/follow/").data == {"following": True, "followers": 1}
    assert api.post(f"/api/users/{creator.id}/follow/").data["followers"] == 1  # idempotent
    assert api.post(f"/api/users/{fan.id}/follow/").status_code == 400  # self
    assert api.post("/api/users/999999/follow/").status_code == 404
    assert APIClient().post(f"/api/users/{creator.id}/follow/").status_code == 401
    assert api.delete(f"/api/users/{creator.id}/follow/").data == {"following": False, "followers": 0}


@pytest.mark.django_db
def test_video_ready_fans_out_to_followers_feeds_once(users, mongo_db):
    creator, fan1, fan2 = users
    client_for(fan1).post(f"/api/users/{creator.id}/follow/")
    client_for(fan2).post(f"/api/users/{creator.id}/follow/")
    video = video_for(creator)

    event = ready(video)
    handle_video_ready(event)
    handle_video_ready(event)  # redelivered
    assert mongo_db.feed_items.count_documents({}) == 2
    assert mongo_db.feed_items.count_documents({"user_id": creator.id}) == 0

    feed = client_for(fan1).get("/api/feed/").data["results"]
    assert [v["id"] for v in feed] == [str(video.id)]
    assert client_for(creator).get("/api/feed/").data["results"] == []


@pytest.mark.django_db
def test_feed_skips_deleted_videos(users, mongo_db):
    creator, fan, _ = users
    client_for(fan).post(f"/api/users/{creator.id}/follow/")
    video = video_for(creator)
    handle_video_ready(ready(video))
    Video.objects.filter(pk=video.pk).delete()
    assert client_for(fan).get("/api/feed/").data["results"] == []


@pytest.mark.django_db
def test_uploader_is_notified_once_per_event(users, mongo_db):
    creator, fan, _ = users
    video = video_for(creator)
    event = ready(video)
    handle_video_event(event)
    handle_video_event(event)  # redelivered
    handle_video_event(kafka.build_event(kafka.VIDEO_FAILED, {"video_id": str(video.id), "error": "Too long."}))
    handle_video_event(kafka.build_event(kafka.VIDEO_READY, {"video_id": str(uuid.uuid4())}))  # deleted video

    api = client_for(creator)
    data = api.get("/api/notifications/").data
    assert data["unread"] == 2
    assert [(n["type"], n["title"], n["error"]) for n in data["results"]] == [
        ("video.failed", "New upload", "Too long."),
        ("video.ready", "New upload", ""),
    ]
    assert data["results"][1]["created_at"].startswith(event["occurred_at"][:19])  # event time, not processing time
    assert client_for(fan).get("/api/notifications/").data == {"unread": 0, "results": []}

    assert api.post("/api/notifications/read/").status_code == 204
    assert api.get("/api/notifications/").data["unread"] == 0


@pytest.mark.django_db
def test_watch_page_shows_follow_state(users):
    creator, fan, _ = users
    video = video_for(creator)
    api = client_for(fan)
    assert api.get(f"/api/videos/{video.id}/").data["is_following"] is False
    api.post(f"/api/users/{creator.id}/follow/")
    data = api.get(f"/api/videos/{video.id}/").data
    assert data["is_following"] is True and data["owner_id"] == creator.id
