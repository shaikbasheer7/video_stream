"""Applies encoder events (video.ready / video.failed) to the database. Idempotent."""

import logging

from django.core.exceptions import ValidationError
from django.db import transaction

from common import kafka

from .models import Rendition, Video

logger = logging.getLogger(__name__)


def apply_event(event):
    kind = event.get("event")
    try:
        if kind == kafka.VIDEO_READY:
            apply_ready(event)
        elif kind == kafka.VIDEO_FAILED:
            apply_failed(event)
        else:
            logger.warning("ignoring unexpected event %r", kind)
    except (KeyError, TypeError, ValueError, ValidationError):
        # Malformed message: retrying won't fix it, so log and move on.
        logger.exception("skipping malformed %s event: %s", kind, event)


@transaction.atomic
def apply_ready(event):
    video = Video.objects.select_for_update().filter(pk=event["video_id"]).first()
    if video is None:
        logger.info("video.ready for deleted video %s", event["video_id"])
        return
    video.status = Video.Status.READY
    video.master_playlist_key = event["master_key"]
    video.duration_sec = event["duration_sec"]
    video.width = event.get("width")
    video.height = event.get("height")
    video.thumbnail_key = event.get("thumbnail_key", "")
    video.error_message = ""
    video.save()
    # Replace rather than append, so a re-delivered or re-encoded event leaves exactly one row per quality.
    video.renditions.all().delete()
    Rendition.objects.bulk_create(
        Rendition(
            video=video,
            quality=r["quality"],
            playlist_key=r["playlist_key"],
            width=r["width"],
            height=r["height"],
            bitrate_kbps=r["bitrate_kbps"],
        )
        for r in event["renditions"]
    )
    logger.info("video %s ready: %s", video.id, [r["quality"] for r in event["renditions"]])


@transaction.atomic
def apply_failed(event):
    video = Video.objects.select_for_update().filter(pk=event["video_id"]).first()
    if video is None or video.status == Video.Status.READY:
        return  # deleted, or a stale failure for a video that has since been encoded
    video.status = Video.Status.FAILED
    video.error_message = str(event.get("error") or "Encoding failed.")[:1000]
    video.save(update_fields=["status", "error_message", "updated_at"])
    logger.info("video %s failed: %s", video.id, video.error_message)
