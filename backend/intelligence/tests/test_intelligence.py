import pytest
from django.db import connection
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from intelligence.models import VideoTag, VideoTranscript
from videos.models import Video

needs_postgres = pytest.mark.skipif(connection.vendor != "postgresql", reason="full-text search needs PostgreSQL")


@pytest.fixture
def owner():
    return User.objects.create_user(email="owner@example.com", password="pw-123456789")


def video(owner, title, description="", status=Video.Status.READY):
    return Video.objects.create(
        owner=owner, title=title, description=description, original_filename="v.mp4", content_type="video/mp4",
        size_bytes=1, source_key="raw/v", status=status,
    )  # fmt: skip


def transcribe(v, text, subtitles_key=""):
    VideoTranscript.objects.create(
        video=v, language="en", text=text, subtitles_key=subtitles_key, model="base", event_id="e",
        created_at=timezone.now(),
    )  # fmt: skip


def tag(v, name, kind=VideoTag.Kind.TOPIC, confidence=0.5):
    VideoTag.objects.create(video=v, tag=name, kind=kind, confidence=confidence)


def search(q):
    return APIClient().get("/api/search/", {"q": q}).data


def titles(data):
    return [r["title"] for r in data["results"]]


@needs_postgres
@pytest.mark.django_db
def test_finds_words_only_said_in_the_video_and_highlights_them(owner):
    v = video(owner, "Clip A")
    transcribe(v, "Today we talk about roasting espresso beans at home.")
    video(owner, "Clip B")
    data = search("espresso")
    assert titles(data) == ["Clip A"]
    assert "[[espresso]]" in data["results"][0]["snippet"]


@needs_postgres
@pytest.mark.django_db
def test_finds_tags_and_stems_words(owner):
    tag(video(owner, "Clip A"), "animals")
    transcribe(video(owner, "Clip B"), "She was cooking dinner.")
    assert titles(search("animal")) == ["Clip A"]
    assert titles(search("cook")) == ["Clip B"]


@needs_postgres
@pytest.mark.django_db
def test_title_ranks_above_transcript_and_has_no_snippet(owner):
    transcribe(video(owner, "Long lecture"), "Then a mention of volcanoes in passing.")
    video(owner, "Volcanoes of Iceland")
    data = search("volcanoes")
    assert titles(data) == ["Volcanoes of Iceland", "Long lecture"]
    assert data["results"][0]["snippet"] is None


@needs_postgres
@pytest.mark.django_db
def test_only_ready_videos_and_moderation_flags_are_not_searchable(owner):
    video(owner, "Secret volcano", status=Video.Status.PROCESSING)
    tag(video(owner, "Ordinary"), "violence", kind=VideoTag.Kind.MODERATION)
    assert search("volcano")["results"] == []
    assert search("violence")["results"] == []


@needs_postgres
@pytest.mark.django_db
def test_hostile_query_text_is_safe(owner):
    video(owner, "Robert'); DROP TABLE videos_video;--")
    assert search("'); DROP TABLE videos_video;--")["query"]  # websearch syntax never raises
    assert search('"unterminated OR -')["results"] == []
    assert Video.objects.count() == 1


@pytest.mark.django_db
def test_short_queries_return_nothing_without_touching_the_search(owner):
    assert search("a") == {"query": "a", "results": []}
    assert search("  ") == {"query": "", "results": []}


@pytest.mark.django_db
def test_detail_shows_topic_tags_and_subtitles_but_not_moderation_flags(owner, settings):
    settings.CDN_BASE_URL = "https://cdn.test"
    v = video(owner, "Clip")
    Video.objects.filter(pk=v.pk).update(master_playlist_key=f"hls/{v.id}/master.m3u8")
    tag(v, "animals", confidence=0.6)
    tag(v, "nature", confidence=0.3)
    tag(v, "violence", kind=VideoTag.Kind.MODERATION)
    transcribe(v, "Hello", subtitles_key=f"hls/{v.id}/subtitles/en.vtt")

    data = APIClient().get(f"/api/videos/{v.id}/").data
    assert data["tags"] == ["animals", "nature"]
    assert data["subtitles"] == [{"language": "en", "url": f"https://cdn.test/hls/{v.id}/subtitles/en.vtt"}]


@pytest.mark.django_db
def test_detail_of_an_unanalysed_video_or_one_without_speech(owner):
    v = video(owner, "Clip")
    Video.objects.filter(pk=v.pk).update(master_playlist_key=f"hls/{v.id}/master.m3u8")
    data = APIClient().get(f"/api/videos/{v.id}/").data
    assert data["tags"] == [] and data["subtitles"] == []
    transcribe(v, "")
    assert APIClient().get(f"/api/videos/{v.id}/").data["subtitles"] == []


@pytest.mark.django_db
def test_deleting_a_video_removes_its_analysis(owner):
    v = video(owner, "Clip")
    tag(v, "animals")
    transcribe(v, "Hello")
    v.delete()
    assert not VideoTag.objects.exists() and not VideoTranscript.objects.exists()
