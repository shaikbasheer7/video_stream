"""Upload lifecycle: presign → browser PUTs to S3 → complete (HEAD check + video.uploaded)."""

import logging
import math

from botocore.exceptions import ClientError
from django.conf import settings
from django.db import transaction
from pymongo.errors import PyMongoError
from rest_framework.exceptions import ValidationError

from common import kafka, mongo, storage

from .models import Video

logger = logging.getLogger(__name__)

# Extension → accepted MIME types. Keep in sync with frontend/src/features/upload/fileRules.ts.
ALLOWED_TYPES = {
    "mp4": {"video/mp4"},
    "mov": {"video/quicktime"},
    "mkv": {"video/x-matroska"},
    "webm": {"video/webm"},
}
MAX_PARTS = 10_000  # S3 limit


def source_key_for(video_id, extension):
    return f"raw/{video_id}/source.{extension}"


def part_size_for(size_bytes):
    """Smallest part size (in whole MiB, at least the default) that keeps the part count within S3's limit."""
    mib = 1024**2
    needed = math.ceil(size_bytes / MAX_PARTS / mib) * mib
    return max(settings.MULTIPART_PART_BYTES, needed)


def start_upload(video):
    """Return the instructions the browser needs to upload the source file straight to S3."""
    if video.size_bytes <= settings.MULTIPART_THRESHOLD_BYTES:
        return {
            "method": "single",
            "url": storage.presign_put(video.source_key, video.content_type, settings.UPLOAD_URL_EXPIRES),
            "headers": {"Content-Type": video.content_type},
            "expires_in": settings.UPLOAD_URL_EXPIRES,
        }

    upload_id = storage.create_multipart_upload(video.source_key, video.content_type)
    video.upload_id = upload_id
    video.save(update_fields=["upload_id", "updated_at"])
    part_size = part_size_for(video.size_bytes)
    part_count = math.ceil(video.size_bytes / part_size)
    return {
        "method": "multipart",
        "part_size": part_size,
        "parts": [
            {
                "part_number": n,
                "url": storage.presign_part(video.source_key, upload_id, n, settings.MULTIPART_URL_EXPIRES),
            }
            for n in range(1, part_count + 1)
        ],
        "expires_in": settings.MULTIPART_URL_EXPIRES,
    }


def complete_upload(video_id, parts=None):
    """Verify the object is in S3, mark the video uploaded, then publish video.uploaded.

    Safe to retry: a video still 'uploaded' (publish failed or never happened) is published again.
    The encoder skips duplicates, so an extra message costs nothing.
    """
    with transaction.atomic():
        video = Video.objects.select_for_update().get(pk=video_id)
        if video.status == Video.Status.UPLOADING:
            _verify_and_mark_uploaded(video, parts)
        elif video.status != Video.Status.UPLOADED:
            return video  # already encoding, ready or failed

    # Published only after the commit: the encoder must never see the event before the row says 'uploaded'.
    kafka.publish(
        kafka.VIDEO_UPLOADED,
        key=video.id,
        payload={
            "video_id": str(video.id),
            "source_key": video.source_key,
            "owner_id": video.owner_id,
            "uploaded_at": video.updated_at.isoformat(),
        },
    )
    return video


def _verify_and_mark_uploaded(video, parts):
    head = storage.head_object(video.source_key)
    # A retried /complete finds a multipart upload already assembled.
    if head is None and video.upload_id:
        if not parts:
            raise ValidationError({"parts": "Part ETags are required to finish a multipart upload."})
        try:
            storage.complete_multipart_upload(video.source_key, video.upload_id, parts)
        except ClientError as exc:
            raise ValidationError({"parts": f"S3 rejected the parts: {exc.response['Error']['Code']}"}) from exc
        head = storage.head_object(video.source_key)

    if head is None:
        raise ValidationError({"detail": "The file was not found in storage. Upload it before completing."})
    if head["ContentLength"] != video.size_bytes:
        raise ValidationError(
            {"detail": f"Uploaded size {head['ContentLength']} does not match declared size {video.size_bytes}."}
        )

    video.status = Video.Status.UPLOADED
    video.upload_id = ""
    video.save(update_fields=["status", "upload_id", "updated_at"])


def delete_video(video):
    """Owner deletes a video: raw upload, HLS output and thumbnail.

    If it is mid-encode, the worker notices the row is gone and removes what it uploaded.
    """
    if video.upload_id:
        storage.abort_multipart_upload(video.source_key, video.upload_id)
    storage.delete_object(video.source_key)
    storage.delete_prefix(f"hls/{video.id}/")
    storage.delete_prefix(f"thumbnails/{video.id}/")
    try:
        # Raw playback_events stay (analytics history, TTL-expired); per-user state goes.
        d = mongo.db()
        d.watch_progress.delete_many({"video_id": str(video.id)})
        d.feed_items.delete_many({"video_id": str(video.id)})
    except PyMongoError:
        logger.warning("could not clean MongoDB state for deleted video %s", video.id)  # feed skips missing videos
    video.delete()
