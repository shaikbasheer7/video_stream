"""MongoDB access (pymongo, no ORM). Collections and their indexes are defined here."""

from functools import cache

from django.conf import settings
from pymongo import ASCENDING, DESCENDING, MongoClient


@cache
def client():
    return MongoClient(settings.MONGO_URL, serverSelectionTimeoutMS=5000, tz_aware=True)


def db():
    return client()[settings.MONGO_DB]


def ensure_indexes(database=None):
    d = database if database is not None else db()
    # Raw events expire after EVENTS_TTL_DAYS; long-term history belongs in the data lake (Phase 10).
    d.playback_events.create_index(
        "received_at", expireAfterSeconds=settings.EVENTS_TTL_DAYS * 86400, name="ttl_received_at"
    )
    d.playback_events.create_index([("video_id", ASCENDING), ("received_at", ASCENDING)], name="video_time")
    d.watch_progress.create_index([("user_id", ASCENDING), ("video_id", ASCENDING)], unique=True, name="user_video")
    d.notifications.create_index([("user_id", ASCENDING), ("created_at", DESCENDING)], name="user_recent")
    d.feed_items.create_index([("user_id", ASCENDING), ("video_id", ASCENDING)], unique=True, name="user_video")
    d.feed_items.create_index([("user_id", ASCENDING), ("created_at", DESCENDING)], name="user_recent")
