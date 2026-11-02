"""Text embeddings for videos. The model loads lazily, and only for videos whose text changed."""

import hashlib
from functools import cache

# The blueprint's sentence-transformers model, run through ONNX by fastembed (no PyTorch: hundreds of MB, not GBs).
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


def video_text(title, description):
    return f"{title}. {description}".strip() if description else title


def text_hash(text):
    return hashlib.sha256(f"{MODEL_NAME}\n{text}".encode()).hexdigest()


@cache
def _model():
    from fastembed import TextEmbedding

    return TextEmbedding(MODEL_NAME)


def embed(texts):
    return [vector.tolist() for vector in _model().embed(list(texts))]


def changed_videos(videos, stored_hashes):
    """videos: [(id, title, description)]. Returns [(id, text, hash)] for those new or edited since the last run."""
    changed = []
    for video_id, title, description in videos:
        text = video_text(title, description or "")
        digest = text_hash(text)
        if stored_hashes.get(video_id) != digest:
            changed.append((video_id, text, digest))
    return changed
