import uuid

from django.conf import settings
from django.db import models


class Video(models.Model):
    class Status(models.TextChoices):
        UPLOADING = "uploading"
        UPLOADED = "uploaded"
        PROCESSING = "processing"
        READY = "ready"
        FAILED = "failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="videos")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.UPLOADING, db_index=True)

    original_filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100)
    size_bytes = models.BigIntegerField()
    source_key = models.CharField(max_length=512)
    # Set while an S3 multipart upload is open; cleared once it completes.
    upload_id = models.CharField(max_length=1024, blank=True)

    # event_id of the video.uploaded message the encoder is working on. Lets the encoder tell a
    # redelivery of that message (take over after a crash) from a duplicate (skip).
    encode_event_id = models.CharField(max_length=64, blank=True)

    # Filled in from video.ready by the status consumer.
    master_playlist_key = models.CharField(max_length=512, blank=True)
    duration_sec = models.FloatField(null=True, blank=True)
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    thumbnail_key = models.CharField(max_length=512, blank=True)
    error_message = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} ({self.status})"


class Rendition(models.Model):
    class Quality(models.TextChoices):
        P480 = "480p"
        P720 = "720p"
        P1080 = "1080p"

    video = models.ForeignKey(Video, on_delete=models.CASCADE, related_name="renditions")
    quality = models.CharField(max_length=10, choices=Quality.choices)
    playlist_key = models.CharField(max_length=512)
    width = models.PositiveIntegerField()
    height = models.PositiveIntegerField()
    bitrate_kbps = models.PositiveIntegerField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["video", "quality"], name="unique_rendition_per_quality")]

    def __str__(self):
        return f"{self.video_id} {self.quality}"
