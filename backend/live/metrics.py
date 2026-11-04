"""Reads the live metrics Spark keeps in Redis (data/pipeline/live.py). Keys expire, so silence means no live data."""

import logging
import time
from functools import cache

import redis
from django.conf import settings

logger = logging.getLogger(__name__)

VIEWERS_KEY = "live:viewers"
TRENDING_KEY = "live:trending"
UPDATED_KEY = "live:updated_at"
# With Redis away, even a failed lookup of its address can take seconds and hold up a web worker. So don't keep trying.
RETRY_AFTER_SEC = 30
_retry_at = 0.0


@cache
def client():
    # Short timeouts: these numbers are a nice extra, and must never slow a page down.
    return redis.Redis.from_url(
        settings.REDIS_URL, socket_connect_timeout=0.3, socket_timeout=0.3, decode_responses=True
    )


def snapshot(trending_limit=12):
    """{"updated_at", "viewers": {video id: count}, "trending": [video ids]}, or None if there's no live data."""
    global _retry_at  # noqa: PLW0603
    if not settings.REDIS_URL or time.monotonic() < _retry_at:
        return None
    try:
        pipe = client().pipeline(transaction=True)
        pipe.get(UPDATED_KEY)
        pipe.hgetall(VIEWERS_KEY)
        pipe.zrevrange(TRENDING_KEY, 0, trending_limit - 1)
        updated_at, viewers, trending = pipe.execute()
    except (redis.RedisError, OSError) as exc:
        logger.warning("live metrics unavailable, not retrying for %d s: %s", RETRY_AFTER_SEC, exc)
        _retry_at = time.monotonic() + RETRY_AFTER_SEC
        return None
    if not updated_at:
        return None
    return {"updated_at": updated_at, "viewers": {k: int(v) for k, v in viewers.items()}, "trending": trending}
