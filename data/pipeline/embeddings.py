"""Text embeddings for videos. The model loads lazily, and only for videos whose text changed."""

import hashlib
from functools import cache

# The blueprint's sentence-transformers model, run through ONNX by fastembed (no PyTorch: hundreds of MB, not GBs).
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
# The model only reads about 256 tokens, so what the uploader wrote comes first and the transcript gets what's left.
MAX_TRANSCRIPT_CHARS = 1000


def video_text(title, description, tags=(), transcript=""):
    parts = [title, description, ", ".join(tags), transcript[:MAX_TRANSCRIPT_CHARS]]
    return ". ".join(part for part in parts if part)


def text_hash(text):
    return hashlib.sha256(f"{MODEL_NAME}\n{text}".encode()).hexdigest()


@cache
def _model():
    from fastembed import TextEmbedding

    return TextEmbedding(MODEL_NAME)


def embed(texts):
    return [vector.tolist() for vector in _model().embed(list(texts))]


def changed_videos(videos, stored_hashes):
    """videos: [(id, title, description, tags, transcript)]. Returns [(id, text, hash)] for those whose text changed.

    That includes a video the ML worker has analysed since the last run.
    """
    changed = []
    for video_id, title, description, tags, transcript in videos:
        text = video_text(title, description or "", tags, transcript)
        digest = text_hash(text)
        if stored_hashes.get(video_id) != digest:
            changed.append((video_id, text, digest))
    return changed
