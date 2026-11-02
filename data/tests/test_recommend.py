from datetime import UTC, datetime, timedelta

import pytest

from pipeline.embeddings import MAX_TRANSCRIPT_CHARS, changed_videos, text_hash, video_text
from pipeline.recommend import recommend_for_user, similar_videos

# Hand-made "embeddings": cooking videos point one way, programming another.
IDS = ["pasta", "pizza", "soup", "python", "rust"]
VECTORS = [[1.0, 0.1], [0.95, 0.2], [0.8, 0.3], [0.1, 1.0], [0.2, 0.95]]
NOW = datetime(2026, 11, 1, tzinfo=UTC)


def watched(video_id, completed=False, days_ago=0):
    return {"video_id": video_id, "completed": completed, "updated_at": NOW - timedelta(days=days_ago)}


def test_similar_videos_ranks_by_closeness_and_never_includes_itself():
    result = similar_videos(IDS, VECTORS, k=2)
    assert [v for v, _ in result["pasta"]] == ["pizza", "soup"]
    assert [v for v, _ in result["python"]] == ["rust", "soup"]
    assert all(v != video for video, picks in result.items() for v, _ in picks)
    assert result["pasta"][0][1] > result["pasta"][1][1]


def test_unrelated_videos_are_not_called_similar():
    result = similar_videos(["a", "b", "c"], [[1.0, 0.0], [1.0, 0.01], [0.0, 1.0]], min_similarity=0.5)
    assert [v for v, _ in result["a"]] == ["b"]
    assert "c" not in result  # nothing close enough: the API falls back to trending


def test_no_videos_and_zero_vectors_are_handled():
    assert similar_videos([], []) == {}
    assert similar_videos(["a", "b"], [[0.0, 0.0], [1.0, 0.0]]) == {}


def test_user_gets_unseen_videos_like_what_they_watched():
    picks = recommend_for_user([watched("pasta")], IDS, VECTORS)
    assert [v for v, _ in picks][:2] == ["pizza", "soup"]
    assert "pasta" not in [v for v, _ in picks]


def test_a_finished_video_outweighs_a_sampled_one():
    tied = [[1.0, 0.0], [0.0, 1.0], [0.9, 0.2], [0.2, 0.9]]
    ids = ["a", "b", "like-a", "like-b"]
    picks = recommend_for_user([watched("a", completed=True), watched("b")], ids, tied)
    assert picks[0][0] == "like-a"


def test_own_uploads_and_anything_started_are_excluded():
    picks = recommend_for_user([watched("pasta"), watched("pizza")], IDS, VECTORS, owned={"soup"}, min_similarity=-1)
    assert {v for v, _ in picks} == {"python", "rust"}


def test_history_with_only_deleted_videos_gives_nothing():
    assert recommend_for_user([watched("gone")], IDS, VECTORS) == []


def test_old_history_beyond_the_limit_no_longer_shapes_taste():
    recent = [watched("python", days_ago=i) for i in range(50)]
    ancient = [watched("pasta", days_ago=1000)]
    assert recommend_for_user(recent + ancient, IDS, VECTORS)[0][0] == "rust"


@pytest.mark.parametrize(("title", "description", "expected"), [("T", "", "T"), ("T", "D", "T. D")])
def test_video_text(title, description, expected):
    assert video_text(title, description) == expected


def test_video_text_adds_tags_and_a_capped_transcript_after_what_the_uploader_wrote():
    assert video_text("T", "D", ["animals", "nature"], "Hello") == "T. D. animals, nature. Hello"
    assert video_text("T", "", (), "x" * 5000) == "T. " + "x" * MAX_TRANSCRIPT_CHARS


def test_only_new_or_edited_videos_are_re_embedded():
    stored = {"same": text_hash("Title. Text"), "edited": text_hash("old title")}
    videos = [
        ("same", "Title", "Text", [], ""),
        ("edited", "new title", None, [], ""),
        ("new", "brand new", "", [], ""),
    ]
    assert [c[0] for c in changed_videos(videos, stored)] == ["edited", "new"]


def test_a_video_is_re_embedded_once_it_has_been_analysed():
    stored = {"v": text_hash("Title")}
    assert changed_videos([("v", "Title", "", [], "")], stored) == []
    assert [c[0] for c in changed_videos([("v", "Title", "", ["animals"], "")], stored)] == ["v"]
