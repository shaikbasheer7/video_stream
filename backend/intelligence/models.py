"""Results of the ML worker (ml/). Written by that worker; Django owns the schema and reads them."""

from django.db import models

from videos.models import Video


class VideoTranscript(models.Model):
    """One row per analysed video, even with no speech: it also marks the analysis as done."""

    video = models.OneToOneField(Video, on_delete=models.CASCADE, primary_key=True, related_name="transcript")
    language = models.CharField(max_length=10, blank=True)
    text = models.TextField(blank=True)
    subtitles_key = models.CharField(max_length=512, blank=True)
    model = models.CharField(max_length=50)
    event_id = models.CharField(max_length=64)  # the video.ready it came from: a redelivery is skipped
    created_at = models.DateTimeField()

    class Meta:
        db_table = "video_transcripts"

    def __str__(self):
        return f"{self.video_id} ({self.language or 'no speech'})"


class VideoTag(models.Model):
    class Kind(models.TextChoices):
        TOPIC = "topic"
        MODERATION = "moderation"  # a flag for human review; never hides a video by itself

    class Source(models.TextChoices):
        CLIP = "clip"
        MANUAL = "manual"

    video = models.ForeignKey(Video, on_delete=models.CASCADE, related_name="tags")
    tag = models.CharField(max_length=50)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.TOPIC)
    confidence = models.FloatField()
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.CLIP)

    class Meta:
        db_table = "video_tags"
        ordering = ["-confidence"]
        constraints = [models.UniqueConstraint(fields=["video", "tag", "kind"], name="unique_video_tag")]
        indexes = [models.Index(fields=["kind", "tag"], name="video_tag_lookup")]

    def __str__(self):
        return f"{self.video_id} {self.kind}:{self.tag}"
