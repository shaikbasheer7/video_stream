import pytest
from rest_framework.test import APIClient

from accounts.models import User
from common import kafka
from videos.models import Video
from videos.status import apply_event


@pytest.fixture
def video():
    owner = User.objects.create_user(email="owner@example.com", password="pw-123456789")
    return Video.objects.create(
        owner=owner,
        title="Clip",
        original_filename="clip.mp4",
        content_type="video/mp4",
        size_bytes=1000,
        source_key="raw/x/source.mp4",
        status=Video.Status.PROCESSING,
    )


def ready_event(video, qualities=("480p", "720p")):
    sizes = {"480p": (854, 480, 1400), "720p": (1280, 720, 2800), "1080p": (1920, 1080, 5000)}
    return kafka.build_event(
        kafka.VIDEO_READY,
        {
            "video_id": str(video.id),
            "master_key": f"hls/{video.id}/master.m3u8",
            "qualities": list(qualities),
            "renditions": [
                {
                    "quality": q,
                    "playlist_key": f"hls/{video.id}/{q}/index.m3u8",
                    "width": sizes[q][0],
                    "height": sizes[q][1],
                    "bitrate_kbps": sizes[q][2],
                }
                for q in qualities
            ],
            "duration_sec": 31.5,
            "width": 1280,
            "height": 720,
            "thumbnail_key": f"thumbnails/{video.id}/default.jpg",
        },
    )


@pytest.mark.django_db
def test_ready_sets_metadata_and_renditions(video):
    apply_event(ready_event(video))
    video.refresh_from_db()
    assert video.status == Video.Status.READY
    assert video.master_playlist_key == f"hls/{video.id}/master.m3u8"
    assert (video.duration_sec, video.width, video.height) == (31.5, 1280, 720)
    assert video.thumbnail_key.endswith("default.jpg")
    assert sorted(video.renditions.values_list("quality", flat=True)) == ["480p", "720p"]


@pytest.mark.django_db
def test_ready_is_idempotent(video):
    apply_event(ready_event(video))
    apply_event(ready_event(video))
    assert video.renditions.count() == 2


@pytest.mark.django_db
def test_failed_sets_error_but_never_overrides_ready(video):
    apply_event(kafka.build_event(kafka.VIDEO_FAILED, {"video_id": str(video.id), "error": "No video stream."}))
    video.refresh_from_db()
    assert (video.status, video.error_message) == (Video.Status.FAILED, "No video stream.")

    apply_event(ready_event(video))
    apply_event(kafka.build_event(kafka.VIDEO_FAILED, {"video_id": str(video.id), "error": "late"}))
    video.refresh_from_db()
    assert video.status == Video.Status.READY


@pytest.mark.django_db
@pytest.mark.parametrize(
    "event",
    [
        {"event": "video.ready", "video_id": "00000000-0000-0000-0000-000000000000", "master_key": "x",
         "duration_sec": 1, "renditions": []},  # deleted video
        {"event": "video.ready", "video_id": "not-a-uuid"},
        {"event": "video.ready"},
        {"event": "something.else"},
    ],
)  # fmt: skip
def test_unknown_or_malformed_events_are_skipped(event):
    apply_event(event)  # must not raise, or the consumer would retry it forever


@pytest.mark.django_db
def test_ready_video_api_shows_thumbnail_and_qualities(video, settings):
    settings.CDN_BASE_URL = "https://cdn.test"
    apply_event(ready_event(video, ("480p", "720p", "1080p")))
    data = APIClient().get("/api/videos/").data["results"][0]
    assert data["status"] == "ready"
    assert data["thumbnail_url"] == f"https://cdn.test/thumbnails/{video.id}/default.jpg"
    assert [r["quality"] for r in data["renditions"]] == ["480p", "720p", "1080p"]
