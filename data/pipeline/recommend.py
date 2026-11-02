"""Content-based recommendations (pure functions over embedding vectors; no I/O).

Blueprint stage two: it needs no watch data to place a new video, unlike collaborative filtering, which is deferred
until there are thousands of users with real history (it does worse than popularity on sparse data).
"""

import numpy as np

SIMILAR_PER_VIDEO = 12
PICKS_PER_USER = 24
# Measured on 24 hand-labelled video titles (171 pairs): 0.2 kept 41% of same-topic pairs and let through 4% of
# different-topic ones; 0.15 kept 66% but let through 11%. Short titles separate poorly, so favour precision: an empty
# list falls back to trending, which beats wrong videos. Re-measure when transcripts and tags join the text (Phase 9).
MIN_SIMILARITY = 0.2
COMPLETED_WEIGHT = 2.0  # finishing a video says more about taste than sampling it
HISTORY_LIMIT = 50  # recent tastes only


def _normalize(matrix):
    norms = np.linalg.norm(matrix, axis=-1, keepdims=True)
    return matrix / np.where(norms == 0, 1, norms)


def similar_videos(video_ids, vectors, k=SIMILAR_PER_VIDEO, min_similarity=MIN_SIMILARITY):
    """{video_id: [(other_id, score), ...]}, best first, never the video itself."""
    if not video_ids:
        return {}
    unit = _normalize(np.asarray(vectors, dtype=float))
    scores = unit @ unit.T
    np.fill_diagonal(scores, -1.0)
    result = {}
    for i, video_id in enumerate(video_ids):
        order = np.argsort(-scores[i])[:k]
        picks = [(video_ids[j], round(float(scores[i][j]), 4)) for j in order if scores[i][j] >= min_similarity]
        if picks:
            result[video_id] = picks
    return result


def recommend_for_user(history, video_ids, vectors, owned=frozenset(), k=PICKS_PER_USER, min_similarity=MIN_SIMILARITY):
    """history: [{"video_id", "completed", "updated_at"}]. Returns [(video_id, score), ...], best first.

    The user's taste is the average of what they watched, weighted towards what they finished. Anything they've
    already started or uploaded themselves is left out: resuming has its own path, and their own videos aren't news.
    """
    index = {video_id: i for i, video_id in enumerate(video_ids)}
    recent = sorted(history, key=lambda h: h["updated_at"], reverse=True)[:HISTORY_LIMIT]
    watched = [h for h in recent if h["video_id"] in index]
    if not watched:
        return []

    unit = _normalize(np.asarray(vectors, dtype=float))
    weights = np.array([COMPLETED_WEIGHT if h.get("completed") else 1.0 for h in watched])
    profile = np.average(unit[[index[h["video_id"]] for h in watched]], axis=0, weights=weights)
    profile = _normalize(profile)

    seen = {h["video_id"] for h in history} | set(owned)
    scores = unit @ profile
    picks = []
    for i in np.argsort(-scores):
        if scores[i] < min_similarity or len(picks) == k:
            break
        if video_ids[i] not in seen:
            picks.append((video_ids[i], round(float(scores[i]), 4)))
    return picks
