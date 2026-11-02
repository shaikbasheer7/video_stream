"""Analytics subscriber (group `analytics`): events.playback → MongoDB.

- playback_events: one document per event, _id = event_id, so redelivery is harmless. TTL-indexed.
- watch_progress: latest position per (user, video), used for resume. Only moves forward in time,
  so out-of-order or replayed events can't overwrite newer progress.
"""

import logging
from datetime import datetime

from pymongo.errors import DuplicateKeyError

from common import mongo

logger = logging.getLogger(__name__)

PROGRESS_TYPES = {"progress", "pause", "seek", "complete"}
EVENT_FIELDS = [
    "type", "video_id", "session_id", "user_id", "anonymous_id", "position_sec", "quality", "device", "country",
    "from_sec", "to_sec", "from_quality", "to_quality", "auto", "duration_ms", "watch_time_sec",
]  # fmt: skip


def handle_playback_event(event):
    try:
        received_at = datetime.fromisoformat(event["received_at"])
        # Clients' clocks drift; never trust a timestamp from the future.
        client_ts = min(datetime.fromisoformat(event["client_ts"]), received_at)
        event_id, event_type, video_id = event["event_id"], event["type"], event["video_id"]
    except (KeyError, TypeError, ValueError):
        logger.warning("skipping malformed playback event: %s", event)
        return

    d = mongo.db()
    # Progress first: if we crash after it, the redelivered event re-applies it harmlessly.
    if event.get("user_id") and event_type in PROGRESS_TYPES:
        update_watch_progress(d, event, client_ts)

    doc = {field: event[field] for field in EVENT_FIELDS if event.get(field) is not None}
    doc.update(_id=event_id, client_ts=client_ts, received_at=received_at, video_id=video_id)
    try:
        d.playback_events.insert_one(doc)
    except DuplicateKeyError:
        pass  # already stored (redelivery)


def update_watch_progress(d, event, ts):
    completed = event["type"] == "complete"
    if completed:
        position = 0.0  # finished: next time start from the beginning
    elif event["type"] == "seek":
        position = event["to_sec"]
    else:
        position = event["position_sec"]
    try:
        d.watch_progress.update_one(
            {"user_id": event["user_id"], "video_id": event["video_id"], "updated_at": {"$lt": ts}},
            {"$set": {"position_sec": position, "completed": completed, "updated_at": ts}},
            upsert=True,
        )
    except DuplicateKeyError:
        pass  # a newer position is already stored, so the filter didn't match and the upsert collided


def resume_position(user_id, video):
    """Where this user left off, or None if they haven't started, finished, or are near the start or end."""
    doc = mongo.db().watch_progress.find_one({"user_id": user_id, "video_id": str(video.id)})
    if not doc or doc.get("completed"):
        return None
    position = doc.get("position_sec", 0)
    if position < 5 or (video.duration_sec and position > video.duration_sec - 10):
        return None
    return round(position, 1)
