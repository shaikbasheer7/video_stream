import numpy as np

from ml import tagging, transcribe
from ml.tagging import pick_flags, pick_thumbnail, pick_topics
from ml.transcribe import Cue, to_webvtt


def unit(*values):
    vector = np.array(values, dtype=float)
    return vector / np.linalg.norm(vector)


def test_webvtt_format_and_timestamps():
    vtt = to_webvtt([Cue(1.5, 3661.25, "Hello"), Cue(3661.25, 3662.0, "World")])
    assert vtt == "WEBVTT\n\n00:00:01.500 --> 01:01:01.250\nHello\n\n01:01:01.250 --> 01:01:02.000\nWorld\n"


def test_webvtt_escapes_markup_in_recognised_speech():
    vtt = to_webvtt([Cue(0, 1, "a <script>x</script> & b --> c")])
    assert "<script>" not in vtt
    assert "a &lt;script&gt;x&lt;/script&gt; &amp; b --&gt; c" in vtt
    assert vtt.count("-->") == 1  # only the timing line


def test_empty_webvtt_is_still_valid():
    assert to_webvtt([]) == "WEBVTT\n"


def test_only_confident_low_probability_segments_count_as_noise():
    assert transcribe.is_speech(no_speech_prob=0.1, avg_logprob=-0.2)
    assert transcribe.is_speech(no_speech_prob=0.9, avg_logprob=-0.2)  # sounds silent, but clearly recognised
    assert transcribe.is_speech(no_speech_prob=0.1, avg_logprob=-1.5)  # hard to hear, but someone is talking
    assert not transcribe.is_speech(no_speech_prob=0.9, avg_logprob=-1.5)


NAMES = ["animals", "cars", "other"]
LABELS = np.array([unit(1, 0, 0), unit(0, 1, 0), unit(0, 0, 1)])


def test_topic_needs_a_confident_average_over_the_video():
    all_cats = np.array([unit(1, 0.05, 0)] * 4)
    assert [t.tag for t in pick_topics(all_cats, LABELS, NAMES)] == ["animals"]
    # One cat frame in four is no reason to call the video animals.
    one_cat = np.array([unit(1, 0.05, 0), unit(0, 0, 1), unit(0, 0, 1), unit(0, 0, 1)])
    assert pick_topics(one_cat, LABELS, NAMES) == []


def test_the_background_label_is_never_a_tag():
    assert pick_topics(np.array([unit(0, 0, 1)]), LABELS, NAMES) == []


def test_at_most_max_topics_and_best_first(monkeypatch):
    monkeypatch.setattr(tagging, "TOPIC_MIN_CONFIDENCE", 0.0)
    names = ["animals", "cars", "music", "sports"]
    labels = np.eye(4)
    frames = np.array([unit(4, 3, 2, 1)])
    picks = pick_topics(frames, labels, names)
    assert [t.tag for t in picks] == ["animals", "cars", "music"]
    assert all(t.kind == "topic" for t in picks)


def test_a_single_bad_frame_raises_a_flag():
    names = ["violence", "safe_scene"]
    labels = np.array([unit(1, 0), unit(0, 1)])
    frames = np.array([unit(0, 1)] * 7 + [unit(1, 0)])
    flags = pick_flags(frames, labels, names)
    assert [(f.tag, f.kind) for f in flags] == [("violence", "moderation")]


def test_an_ordinary_video_raises_no_flag_and_safe_labels_are_never_flags():
    names = ["violence", "safe_scene"]
    labels = np.array([unit(1, 0), unit(0, 1)])
    assert pick_flags(np.array([unit(0, 1)] * 8), labels, names) == []


THUMB_NAMES = ["good", "dark"]
THUMB_LABELS = np.array([unit(1, 0), unit(0, 1)])


def test_the_most_thumbnail_like_frame_wins():
    frames = np.array([unit(0, 1), unit(1, 0.05), unit(1, 0.2)])
    assert pick_thumbnail(frames, THUMB_LABELS, THUMB_NAMES) == 1


def test_no_thumbnail_when_every_frame_looks_bad():
    assert pick_thumbnail(np.array([unit(0, 1)] * 3), THUMB_LABELS, THUMB_NAMES) is None
