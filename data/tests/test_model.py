"""The real embedding model, end to end. Skipped where it isn't cached (it runs inside the Airflow image)."""

import os

import pytest

from pipeline.embeddings import embed
from pipeline.recommend import similar_videos

pytestmark = pytest.mark.skipif(not os.environ.get("FASTEMBED_CACHE_PATH"), reason="needs the downloaded model")

CATALOGUE = {
    "pasta": "Easy homemade pasta. Fresh Italian recipe with tomato sauce for beginners",
    "pizza": "How to make Neapolitan pizza at home. Dough, sauce and baking tips",
    "python": "Python tutorial for beginners. Learn programming with variables and loops",
    "rust": "Intro to the Rust programming language. Ownership and memory safety",
    "volcano": "Volcanoes of Iceland. A documentary about eruptions and geology",
}
TOPICS = {"pasta": "food", "pizza": "food", "python": "code", "rust": "code", "volcano": "nature"}


def test_real_embeddings_find_strong_matches_and_show_no_wrong_ones():
    vectors = embed(CATALOGUE.values())
    assert len(vectors[0]) == 384

    similar = similar_videos(list(CATALOGUE), vectors)
    assert similar["pasta"][0][0] == "pizza"
    assert similar["pizza"][0][0] == "pasta"
    # This model is weak on short text: Python <-> Rust scores below the cutoff here, so they get trending instead.
    # That's acceptable. What must never happen is showing a video from another topic as "similar".
    for video, picks in similar.items():
        assert all(TOPICS[other] == TOPICS[video] for other, _ in picks), (video, picks)
