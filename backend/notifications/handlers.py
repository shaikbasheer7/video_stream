"""Notification subscriber (group `notify`): video.ready / video.failed → in-app notification for the uploader.

Email can be added later as another step here.
"""

import logging
from datetime import UTC, datetime

from django.core.exceptions import ValidationError
from pymongo.errors import DuplicateKeyError

from common import kafka, mongo
from videos.models import Video

logger = logging.getLogger(__name__)


def handle_video_event(event):
    kind = event.get("event")
    if kind not in (kafka.VIDEO_READY, kafka.VIDEO_FAILED):
        return
    try:
        video = Video.objects.filter(pk=event["video_id"]).first()
        event_id = event["event_id"]
        # When it happened, not when we processed it (matters after a backlog or replay).
        occurred_at = datetime.fromisoformat(event["occurred_at"]) if event.get("occurred_at") else datetime.now(UTC)
    except (KeyError, ValueError, ValidationError):
        logger.warning("skipping malformed %s event: %s", kind, event)
        return
    if video is None:
        return  # deleted meanwhile

    try:
        mongo.db().notifications.insert_one(
            {
                "_id": event_id,  # one notification per event, even if the event is redelivered
                "user_id": video.owner_id,
                "type": kind,
                "video_id": str(video.id),
                "title": video.title,
                "error": event.get("error", "") if kind == kafka.VIDEO_FAILED else "",
                "read": False,
                "created_at": occurred_at,
            }
        )
    except DuplicateKeyError:
        pass
