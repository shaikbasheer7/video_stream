"""Nightly recommendation jobs: read inputs, call the pure functions, replace the tables atomically."""

import logging
from datetime import UTC, datetime, timedelta

from psycopg.types.json import Jsonb

from . import embeddings, io, recommend

logger = logging.getLogger(__name__)

MODEL_VERSION = "content-minilm-v1"
LIST_SIZE = 50
TRENDING_DAYS = 7
TRENDING_DECAY = 0.7  # a view from yesterday counts 0.7 of today's, from two days ago 0.49...
POPULAR_DAYS = 30

# Pure SQL over the daily tables (blueprint stage one). Deleted or unready videos never make the list.
RANKED_SQL = """
INSERT INTO ranked_videos (list_name, rank, video_id, score, generated_at)
SELECT %(list)s, row_number() OVER (ORDER BY score DESC, video_id), video_id, score, %(now)s
  FROM (
    SELECT s.video_id, SUM({score}) AS score
      FROM daily_video_stats s
      JOIN videos_video v ON v.id = s.video_id AND v.status = 'ready'
     WHERE s.date > %(day)s::date - %(days)s AND s.date <= %(day)s
     GROUP BY s.video_id
  ) ranked
 WHERE score > 0
 ORDER BY score DESC, video_id
 LIMIT %(limit)s
"""
TRENDING_SCORE = "s.views * power(%(decay)s::float, %(day)s::date - s.date)"
POPULAR_SCORE = "s.watch_time_sec"


def refresh_ranked_lists(day):
    """Trending favours recent views; popular is total watch time, which a clickbait title can't fake."""
    now = datetime.now(UTC)
    with io.postgres() as conn:
        conn.execute("DELETE FROM ranked_videos")
        common = {"now": now, "day": day, "limit": LIST_SIZE}
        conn.execute(
            RANKED_SQL.format(score=TRENDING_SCORE),
            {**common, "list": "trending", "days": TRENDING_DAYS, "decay": TRENDING_DECAY},
        )
        conn.execute(RANKED_SQL.format(score=POPULAR_SCORE), {**common, "list": "popular", "days": POPULAR_DAYS})
        counts = dict(conn.execute("SELECT list_name, count(*) FROM ranked_videos GROUP BY 1").fetchall())
    logger.info("ranked lists: %s", counts)
    return counts


def _ready_videos(conn):
    """With what the ML worker found, if it ran. Moderation flags are for reviewers, not for matching videos."""
    rows = conn.execute(
        """SELECT v.id, v.title, v.description,
                  ARRAY(SELECT t.tag FROM video_tags t
                         WHERE t.video_id = v.id AND t.kind = 'topic' ORDER BY t.tag),
                  COALESCE(tr.text, '')
             FROM videos_video v
             LEFT JOIN video_transcripts tr ON tr.video_id = v.id
            WHERE v.status = 'ready'"""
    ).fetchall()
    return [(str(r[0]), r[1], r[2], r[3], r[4]) for r in rows]


def refresh_embeddings():
    """Embed only what changed, and forget videos that are gone. Returns counts."""
    with io.postgres() as conn:
        videos = _ready_videos(conn)
        stored = {str(r[0]): r[1] for r in conn.execute("SELECT video_id, text_hash FROM video_embeddings").fetchall()}
    changed = embeddings.changed_videos(videos, stored)
    vectors = embeddings.embed([text for _, text, _ in changed]) if changed else []

    now = datetime.now(UTC)
    current = {video[0] for video in videos}
    with io.postgres() as conn, conn.cursor() as cur:
        gone = [video_id for video_id in stored if video_id not in current]
        replaced = [video_id for video_id, _, _ in changed]
        cur.execute("DELETE FROM video_embeddings WHERE video_id = ANY(%s::uuid[])", (gone + replaced,))
        cur.executemany(
            """INSERT INTO video_embeddings (video_id, text_hash, model, vector, updated_at)
               VALUES (%s, %s, %s, %s, %s)""",
            [
                (video_id, digest, embeddings.MODEL_NAME, Jsonb(vector), now)
                for (video_id, _, digest), vector in zip(changed, vectors, strict=True)
            ],
        )
    result = {"videos": len(videos), "embedded": len(changed), "removed": len(gone)}
    logger.info("embeddings: %s", result)
    return result


def _load_vectors(conn):
    rows = conn.execute(
        """SELECT e.video_id, e.vector, v.owner_id FROM video_embeddings e
             JOIN videos_video v ON v.id = e.video_id AND v.status = 'ready'
            ORDER BY e.video_id"""
    ).fetchall()
    return [str(r[0]) for r in rows], [r[1] for r in rows], {str(r[0]): r[2] for r in rows}


def publish_similar_videos():
    now = datetime.now(UTC)
    with io.postgres() as conn, conn.cursor() as cur:
        ids, vectors, _ = _load_vectors(conn)
        similar = recommend.similar_videos(ids, vectors)
        cur.execute("DELETE FROM similar_videos")
        cur.executemany(
            """INSERT INTO similar_videos (video_id, similar_video_id, rank, score, model_version, generated_at)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            [
                (video_id, other, rank, score, MODEL_VERSION, now)
                for video_id, picks in similar.items()
                for rank, (other, score) in enumerate(picks, start=1)
            ],
        )
    result = {"videos_with_similar": len(similar), "videos": len(ids)}
    logger.info("similar videos: %s", result)
    return result


def read_watch_history(days=90):
    """{user_id: [{"video_id", "completed", "updated_at"}]} from MongoDB's watch_progress."""
    since = datetime.now(UTC) - timedelta(days=days)
    collection = io.mongo_collection().database.watch_progress
    history = {}
    for doc in collection.find({"updated_at": {"$gte": since}}):
        history.setdefault(doc["user_id"], []).append(
            {"video_id": doc["video_id"], "completed": doc.get("completed", False), "updated_at": doc["updated_at"]}
        )
    return history


def publish_recommendations():
    now = datetime.now(UTC)
    history = read_watch_history()
    with io.postgres() as conn, conn.cursor() as cur:
        ids, vectors, owners = _load_vectors(conn)
        rows = []
        for user_id, watched in history.items():
            owned = {video_id for video_id, owner in owners.items() if owner == user_id}
            picks = recommend.recommend_for_user(watched, ids, vectors, owned=owned)
            rows += [(user_id, v, rank, score, MODEL_VERSION, now) for rank, (v, score) in enumerate(picks, start=1)]
        # Replaced wholesale: someone whose history aged out falls back to trending.
        cur.execute("DELETE FROM recommendations")
        cur.executemany(
            """INSERT INTO recommendations (user_id, video_id, rank, score, model_version, generated_at)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            rows,
        )
    result = {"users_with_history": len(history), "users_with_picks": len({r[0] for r in rows}), "rows": len(rows)}
    logger.info("recommendations: %s", result)
    return result


def run_all(day):
    refresh_ranked_lists(day)
    refresh_embeddings()
    publish_similar_videos()
    publish_recommendations()
