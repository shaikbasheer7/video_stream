"""Zero-shot tagging of video frames with CLIP (ONNX through fastembed, no PyTorch).

CLIP compares a frame with a sentence: each label below is a sentence, and softmax turns the similarities into
shares of 1 per frame. So a confidence is relative to these labels, not a calibrated probability.
"""

from dataclasses import dataclass
from functools import cache
from pathlib import Path

import numpy as np

from . import config

VISION_MODEL = "Qdrant/clip-ViT-B-32-vision"
TEXT_MODEL = "Qdrant/clip-ViT-B-32-text"
LOGIT_SCALE = 100.0  # CLIP's trained temperature

TOPICS = {
    "animals": "a photo of an animal",
    "cooking": "a photo of food or cooking in a kitchen",
    "cars": "a photo of a car or a motorcycle",
    "sports": "a photo of people playing a sport",
    "music": "a photo of a musician playing an instrument",
    "nature": "a photo of a natural landscape",
    "city": "a photo of a city street with buildings",
    "technology": "a photo of a computer or an electronic device",
    "space": "a photo of a rocket or outer space",
    "gaming": "a screenshot of a video game",
    "education": "a photo of a lecture or a presentation slide",
    "people": "a photo of a person talking to the camera",
}
# Soak up frames matching no topic, otherwise a test card or a hammer would still get a confident tag.
TOPIC_BACKGROUND = {
    "other": "an abstract image, a blank screen or a test pattern",
    "object": "a photo of an everyday object or a tool",
}
TOPIC_MIN_CONFIDENCE = 0.4  # measured on real photos: see README
MAX_TOPICS = 3

MODERATION = {
    "nudity": "an explicit photo containing nudity",
    "violence": "a graphic photo of violence and blood",
    "weapons": "a photo of a person holding a gun or a weapon",
}
# Flags compete against ordinary content, so a holiday video isn't "the closest thing to violence".
MODERATION_BACKGROUND = {
    "safe_people": "a photo of a clothed person",
    "safe_scene": "an ordinary photo of a place or an animal",
    "safe_food": "a photo of food on a plate",
    "safe_object": "a photo of an everyday object, clothing or a musical instrument",
    "safe_screen": "a screenshot, a slide or a drawing",
}
# One bad frame is enough, so flags use the worst frame and a high bar. They only queue a video for human review.
MODERATION_MIN_CONFIDENCE = 0.7

THUMBNAIL = {"good": "a sharp, well lit photo with a clear subject"}
THUMBNAIL_BACKGROUND = {
    "dark": "a dark or black frame",
    "blurry": "a blurry, out of focus frame",
    "blank": "a blank screen or a fade between two scenes",
}
THUMBNAIL_MIN_CONFIDENCE = 0.1  # below this the encoder's own thumbnail stays: see README


@dataclass(frozen=True)
class Tag:
    tag: str
    kind: str
    confidence: float


@dataclass(frozen=True)
class FrameAnalysis:
    tags: list
    thumbnail: Path | None  # the frame to use instead of the encoder's thumbnail, if any


def _softmax(scores):
    scores = scores - scores.max(axis=1, keepdims=True)
    exponentials = np.exp(scores)
    return exponentials / exponentials.sum(axis=1, keepdims=True)


def _shares(frames, labels):
    """frames: n x d, labels: m x d, both unit length. Returns n x m, each row summing to 1."""
    return _softmax(LOGIT_SCALE * frames @ labels.T)


def pick_topics(frames, labels, names):
    """Topics confident on average over the video, best first. `names` lists the columns of `labels`."""
    means = _shares(frames, labels).mean(axis=0)
    picks = [(means[i], name) for i, name in enumerate(names) if name in TOPICS and means[i] >= TOPIC_MIN_CONFIDENCE]
    return [Tag(name, "topic", round(float(score), 4)) for score, name in sorted(picks, reverse=True)[:MAX_TOPICS]]


def pick_flags(frames, labels, names):
    worst = _shares(frames, labels).max(axis=0)
    return [
        Tag(name, "moderation", round(float(worst[i]), 4))
        for i, name in enumerate(names)
        if name in MODERATION and worst[i] >= MODERATION_MIN_CONFIDENCE
    ]


def pick_thumbnail(frames, labels, names):
    """Index of the frame most like a good thumbnail, or None if none of them clearly is."""
    scores = _shares(frames, labels)[:, names.index("good")]
    best = int(scores.argmax())
    return best if scores[best] >= THUMBNAIL_MIN_CONFIDENCE else None


def _unit(vectors):
    matrix = np.asarray(list(vectors), dtype=float)
    return matrix / np.linalg.norm(matrix, axis=1, keepdims=True)


@cache
def _vision_model():
    from fastembed import ImageEmbedding

    return ImageEmbedding(VISION_MODEL, cache_dir=config.MODELS_DIR, threads=config.CPU_THREADS)


@cache
def _label_vectors():
    """The sentences never change, so they are embedded once and the text model is then released."""
    from fastembed import TextEmbedding

    model = TextEmbedding(TEXT_MODEL, cache_dir=config.MODELS_DIR, threads=config.CPU_THREADS)
    groups = (
        {**TOPICS, **TOPIC_BACKGROUND},
        {**MODERATION, **MODERATION_BACKGROUND},
        {**THUMBNAIL, **THUMBNAIL_BACKGROUND},
    )
    return tuple((_unit(model.embed(list(group.values()))), list(group)) for group in groups)


def analyse_frames(paths):
    """[frame file] -> FrameAnalysis. No frames, no results."""
    if not paths:
        return FrameAnalysis([], None)
    frames = _unit(_vision_model().embed([str(path) for path in paths]))
    topics, moderation, thumbnail = _label_vectors()
    flags = pick_flags(frames, *moderation)
    # A flagged video waits for a human: the worker doesn't go looking for its most eye-catching frame.
    best = None if flags else pick_thumbnail(frames, *thumbnail)
    return FrameAnalysis(pick_topics(frames, *topics) + flags, None if best is None else Path(paths[best]))
