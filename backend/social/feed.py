"""Feed subscriber (group `feed`): video.ready → the video lands in every follower's feed (fan-out on write)."""

import logging
from datetime import UTC, datetime

from django.core.exceptions import ValidationError
from pymongo import UpdateOne

from common import kafka, mongo
from videos.models import Video

from .models import Follow

logger = logging.getLogger(__name__)
CHUNK = 1000


def handle_video_ready(event):
    if event.get("event") != kafka.VIDEO_READY:
        return
    try:
        video = Video.objects.filter(pk=event["video_id"]).first()
    except (KeyError, ValueError, ValidationError):
        logger.warning("skipping malformed video.ready: %s", event)
        return
    if video is None:
        return

    now = datetime.now(UTC)
    followers = Follow.objects.filter(followee_id=video.owner_id).values_list("follower_id", flat=True)
    batch = []
    for follower_id in followers.iterator(chunk_size=CHUNK):
        # Upsert on (user, video): replaying the event doesn't duplicate feed items.
        batch.append(
            UpdateOne(
                {"user_id": follower_id, "video_id": str(video.id)},
                {"$setOnInsert": {"owner_id": video.owner_id, "created_at": now}},
                upsert=True,
            )
        )
        if len(batch) == CHUNK:
            mongo.db().feed_items.bulk_write(batch, ordered=False)
            batch = []
    if batch:
        mongo.db().feed_items.bulk_write(batch, ordered=False)
