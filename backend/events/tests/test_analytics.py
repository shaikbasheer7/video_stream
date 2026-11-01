import uuid
from datetime import UTC, datetime, timedelta

import pytest
from rest_framework.test import APIClient

from accounts.models import User
from events.analytics import handle_playback_event, resume_position
from videos.models import Video

T0 = datetime(2026, 11, 1, 10, 0, tzinfo=UTC)
VIDEO = str(uuid.uuid4())


def playback(type_="progress", position=30.0, at=0, user_id=7, **extra):
    ts = T0 + timedelta(seconds=at)
    return {
        "event": "playback", "event_id": str(uuid.uuid4()), "type": type_, "video_id": VIDEO,
        "session_id": "s-1", "user_id": user_id, "anonymous_id": "anon", "position_sec": position,
        "quality": "720p", "device": "desktop", "country": None,
        "client_ts": ts.isoformat(), "received_at": (T0 + timedelta(seconds=at + 1)).isoformat(), **extra,
    }  # fmt: skip


def progress(mongo_db, user_id=7):
    return mongo_db.watch_progress.find_one({"user_id": user_id, "video_id": VIDEO})


def test_stores_raw_event_once(mongo_db):
    e = playback()
    handle_playback_event(e)
    handle_playback_event(e)  # redelivered
    assert mongo_db.playback_events.count_documents({}) == 1
    doc = mongo_db.playback_events.find_one({"_id": e["event_id"]})
    assert doc["type"] == "progress" and doc["video_id"] == VIDEO and doc["received_at"].year == 2026


def test_ttl_index_exists(mongo_db):
    ttl = mongo_db.playback_events.index_information()["ttl_received_at"]
    assert ttl["expireAfterSeconds"] == 90 * 86400


def test_progress_tracks_latest_position_and_ignores_older_events(mongo_db):
    handle_playback_event(playback(position=30, at=30))
    handle_playback_event(playback("pause", position=42, at=42))
    handle_playback_event(playback(position=20, at=20))  # arrives late: must not move progress back
    assert progress(mongo_db)["position_sec"] == 42


def test_seek_uses_target_and_complete_resets(mongo_db):
    handle_playback_event(playback("seek", position=10, at=10, from_sec=10, to_sec=95))
    assert progress(mongo_db)["position_sec"] == 95
    handle_playback_event(playback("complete", position=118, at=118, watch_time_sec=110))
    assert progress(mongo_db)["position_sec"] == 0 and progress(mongo_db)["completed"] is True


def test_anonymous_and_non_progress_events_store_no_progress(mongo_db):
    handle_playback_event(playback(user_id=None))
    handle_playback_event(playback("buffering", duration_ms=800))
    handle_playback_event(playback("quality_change", from_quality="480p", to_quality="720p", auto=True))
    assert mongo_db.watch_progress.count_documents({}) == 0
    assert mongo_db.playback_events.count_documents({}) == 3


def test_future_client_clock_is_clamped(mongo_db):
    handle_playback_event(playback(position=50, at=0) | {"client_ts": (T0 + timedelta(days=30)).isoformat()})
    handle_playback_event(playback(position=60, at=5))  # real later event still wins
    assert progress(mongo_db)["position_sec"] == 60


def test_malformed_events_are_skipped(mongo_db):
    handle_playback_event({"event": "playback"})
    handle_playback_event(playback() | {"client_ts": "yesterday"})
    assert mongo_db.playback_events.count_documents({}) == 0


@pytest.mark.django_db
def test_resume_position_rules_and_api(mongo_db):
    user = User.objects.create_user(email="v@example.com", password="pw-123456789")
    video = Video.objects.create(
        id=VIDEO, owner=user, title="T", original_filename="t.mp4", content_type="video/mp4", size_bytes=1,
        source_key="raw/t", status=Video.Status.READY, duration_sec=120, master_playlist_key=f"hls/{VIDEO}/master.m3u8",
    )  # fmt: skip

    def at(position, completed=False):
        mongo_db.watch_progress.replace_one(
            {"user_id": user.id, "video_id": VIDEO},
            {"user_id": user.id, "video_id": VIDEO, "position_sec": position, "completed": completed,
             "updated_at": T0},
            upsert=True,
        )  # fmt: skip
        return resume_position(user.id, video)

    assert resume_position(user.id, video) is None  # never watched
    assert at(3) is None  # barely started
    assert at(115) is None  # practically finished
    assert at(0, completed=True) is None
    assert at(61.27) == 61.3

    client = APIClient()
    client.force_authenticate(user)
    data = client.get(f"/api/videos/{VIDEO}/").data
    assert data["resume_position_sec"] == 61.3
    assert data["is_following"] is False
    assert "resume_position_sec" not in APIClient().get(f"/api/videos/{VIDEO}/").data  # anonymous
