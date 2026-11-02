import uuid

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from recommendations.models import RankedVideo, Recommendation, SimilarVideo
from videos.models import Video


@pytest.fixture
def owner():
    return User.objects.create_user(email="owner@example.com", password="pw-123456789")


def video(owner, title, status=Video.Status.READY):
    return Video.objects.create(
        owner=owner, title=title, original_filename="v.mp4", content_type="video/mp4", size_bytes=1,
        source_key="raw/v", status=status,
    )  # fmt: skip


def rank(list_name, *videos):
    for i, v in enumerate(videos, start=1):
        RankedVideo.objects.create(
            list_name=list_name, rank=i, video_id=v.id, score=10 - i, generated_at=timezone.now()
        )


def recommend(user, *videos):
    for i, v in enumerate(videos, start=1):
        Recommendation.objects.create(
            user_id=user.id, video_id=v.id, rank=i, score=1 - i / 10, model_version="t", generated_at=timezone.now()
        )


def similar_to(base, *videos):
    for i, v in enumerate(videos, start=1):
        SimilarVideo.objects.create(
            video_id=base.id, similar_video_id=v.id, rank=i, score=0.9, model_version="t", generated_at=timezone.now()
        )


def titles(response):
    return [v["title"] for v in response.data["results"]]


@pytest.mark.django_db
def test_new_site_falls_back_to_newest_videos(owner):
    video(owner, "older")
    video(owner, "newer")
    video(owner, "still encoding", status=Video.Status.PROCESSING)
    response = APIClient().get("/api/recommendations/")
    assert response.data["source"] == "latest"
    assert titles(response) == ["newer", "older"]


@pytest.mark.django_db
def test_anonymous_viewers_get_trending_in_rank_order(owner):
    a, b = video(owner, "a"), video(owner, "b")
    rank("trending", b, a)
    response = APIClient().get("/api/recommendations/")
    assert response.data["source"] == "trending"
    assert titles(response) == ["b", "a"]


@pytest.mark.django_db
def test_logged_in_viewer_gets_their_own_picks_or_else_trending(owner):
    a, b = video(owner, "a"), video(owner, "b")
    rank("trending", a)
    viewer, other = (User.objects.create_user(email=f"{n}@example.com", password="pw-123456789") for n in "vo")
    recommend(viewer, b)

    client = APIClient()
    client.force_authenticate(viewer)
    response = client.get("/api/recommendations/")
    assert response.data["source"] == "personalized" and titles(response) == ["b"]

    client.force_authenticate(other)
    assert client.get("/api/recommendations/").data["source"] == "trending"


@pytest.mark.django_db
def test_videos_deleted_or_unready_since_the_last_run_drop_out(owner):
    a, b, c = video(owner, "a"), video(owner, "b"), video(owner, "c")
    rank("trending", a, b, c)
    b.delete()
    Video.objects.filter(pk=c.pk).update(status=Video.Status.FAILED)
    assert titles(APIClient().get("/api/recommendations/trending/")) == ["a"]


@pytest.mark.django_db
def test_popular_list_and_limit(owner):
    vs = [video(owner, str(i)) for i in range(5)]
    rank("popular", *vs)
    assert titles(APIClient().get("/api/recommendations/popular/?limit=2")) == ["0", "1"]
    assert len(APIClient().get("/api/recommendations/popular/?limit=bad").data["results"]) == 5
    assert APIClient().get("/api/recommendations/trending/").data["results"] == []


@pytest.mark.django_db
def test_similar_videos_with_trending_fallback_that_excludes_the_video_itself(owner):
    a, b, c = video(owner, "a"), video(owner, "b"), video(owner, "c")
    similar_to(a, c)
    response = APIClient().get(f"/api/videos/{a.id}/similar/")
    assert response.data["source"] == "similar" and titles(response) == ["c"]

    rank("trending", b, a, c)
    response = APIClient().get(f"/api/videos/{b.id}/similar/?limit=2")
    assert response.data["source"] == "trending" and titles(response) == ["a", "c"]


@pytest.mark.django_db
def test_similar_404s_for_missing_or_unready_videos(owner):
    assert APIClient().get(f"/api/videos/{uuid.uuid4()}/similar/").status_code == 404
    hidden = video(owner, "private", status=Video.Status.PROCESSING)
    assert APIClient().get(f"/api/videos/{hidden.id}/similar/").status_code == 404
