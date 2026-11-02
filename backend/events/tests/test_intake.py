import uuid
from datetime import timedelta

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from accounts.models import User
from common import kafka

VIDEO = str(uuid.uuid4())


@pytest.fixture
def published(monkeypatch):
    batches = []

    def fake_publish_many(topic, messages, event=None, timeout=10.0):
        batches.append([(topic, key, kafka.build_event(event or topic, payload)) for key, payload in messages])

    monkeypatch.setattr(kafka, "publish_many", fake_publish_many)
    return batches


def event(type_="progress", **extra):
    return {"type": type_, "video_id": VIDEO, "session_id": "s-1", "ts": "2026-11-01T10:00:00Z",
            "position_sec": 12.5, "quality": "720p", **extra}  # fmt: skip


def post(client, events, **params):
    query = "?" + "&".join(f"{k}={v}" for k, v in params.items()) if params else ""
    return client.post(f"/api/events/batch/{query}", {"anonymous_id": "anon-1", "events": events}, format="json")


@pytest.mark.django_db
def test_anonymous_batch_is_published_keyed_by_video(published):
    client = APIClient(HTTP_USER_AGENT="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) Mobile/15E148")
    response = post(client, [event("play", position_sec=0), event(), event("seek", from_sec=12.5, to_sec=40)])

    assert response.status_code == 202
    assert response.data == {"accepted": 3}
    [batch] = published
    assert [(t, k) for t, k, _ in batch] == [("events.playback", VIDEO)] * 3
    msg = batch[2][2]
    assert msg["event"] == "playback" and msg["type"] == "seek"
    assert (msg["from_sec"], msg["to_sec"]) == (12.5, 40)
    assert msg["user_id"] is None and msg["anonymous_id"] == "anon-1"
    assert msg["device"] == "mobile"
    assert msg["client_ts"].startswith("2026-11-01T10:00:00")
    assert msg["received_at"] and msg["event_id"] and msg["schema_version"] == 1
    assert len({m["event_id"] for _, _, m in batch}) == 3


@pytest.mark.django_db
def test_logged_in_events_carry_user_id(published):
    user = User.objects.create_user(email="v@example.com", password="pw-123456789")
    client = APIClient()
    client.force_authenticate(user)
    post(client, [event()])
    assert published[0][0][2]["user_id"] == user.id


@pytest.mark.django_db
@pytest.mark.parametrize(
    "bad",
    [
        [],  # empty
        [event()] * 101,  # too many
        [event("dance")],  # unknown type
        [event(video_id="nope")],
        [event("seek")],  # seek without from/to
        [event(position_sec=-1)],
    ],
)
def test_rejects_invalid_batches(published, bad):
    assert post(APIClient(), bad).status_code == 400
    assert published == []


@pytest.mark.django_db
def test_expired_token_401s_normally_but_final_flush_is_kept_anonymously(published):
    user = User.objects.create_user(email="v@example.com", password="pw-123456789")
    token = AccessToken.for_user(user)
    token.set_exp(lifetime=-timedelta(seconds=1))
    client = APIClient(HTTP_AUTHORIZATION=f"Bearer {token}")

    assert post(client, [event()]).status_code == 401  # client refreshes and retries
    assert post(client, [event()], final=1).status_code == 202  # page is closing: keep the data
    assert published[0][0][2]["user_id"] is None


@pytest.mark.django_db
def test_kafka_down_is_503(monkeypatch):
    def broken(*args, **kwargs):
        raise kafka.PublishError("down")

    monkeypatch.setattr(kafka, "publish_many", broken)
    assert post(APIClient(), [event()]).status_code == 503
