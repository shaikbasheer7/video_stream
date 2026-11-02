"""Daily aggregates written by the Airflow pipeline (data/pipeline) and read by Superset.

Django owns the schema (every change is a migration); the app itself never writes these tables. video_id is a
plain UUID, not a foreign key: analytics history outlives a deleted video.
"""

from django.db import models


class DailyVideoStats(models.Model):
    date = models.DateField()
    video_id = models.UUIDField()
    views = models.PositiveIntegerField()  # playback sessions with a play event
    unique_viewers = models.PositiveIntegerField()
    watch_time_sec = models.FloatField()
    avg_completion_pct = models.FloatField(null=True)  # null when the video's duration is unknown (deleted)
    completions = models.PositiveIntegerField()  # sessions that reached 95%
    buffering_events = models.PositiveIntegerField()  # stalls after playback started
    buffering_ms = models.BigIntegerField()

    class Meta:
        db_table = "daily_video_stats"
        constraints = [models.UniqueConstraint(fields=["date", "video_id"], name="unique_daily_video")]
        indexes = [models.Index(fields=["video_id", "date"], name="daily_video_lookup")]

    def __str__(self):
        return f"{self.date} {self.video_id}"


class DailyVideoRetention(models.Model):
    """Audience retention curve: how many sessions watched each 5% slice of the video."""

    date = models.DateField()
    video_id = models.UUIDField()
    position_pct = models.PositiveSmallIntegerField()  # start of the slice: 0, 5, ... 95
    viewers = models.PositiveIntegerField()

    class Meta:
        db_table = "daily_video_retention"
        constraints = [models.UniqueConstraint(fields=["date", "video_id", "position_pct"], name="unique_retention")]

    def __str__(self):
        return f"{self.date} {self.video_id} @{self.position_pct}%"


class DailyStreamingQuality(models.Model):
    date = models.DateField()
    device = models.CharField(max_length=20)
    country = models.CharField(max_length=8)
    quality = models.CharField(max_length=10)
    sessions = models.PositiveIntegerField()
    watch_time_sec = models.FloatField()
    buffering_events = models.PositiveIntegerField()  # stalls after playback started
    buffering_ms = models.BigIntegerField()
    startup_events = models.PositiveIntegerField()  # waiting before the first frames played
    startup_ms = models.BigIntegerField()
    quality_changes = models.PositiveIntegerField()

    class Meta:
        db_table = "daily_streaming_quality"
        constraints = [
            models.UniqueConstraint(fields=["date", "device", "country", "quality"], name="unique_daily_quality")
        ]

    def __str__(self):
        return f"{self.date} {self.device}/{self.country}/{self.quality}"


class DailyPlatformStats(models.Model):
    # Stored rather than summed: a viewer of two videos is one unique viewer across the platform.
    date = models.DateField(primary_key=True)
    views = models.PositiveIntegerField()
    sessions = models.PositiveIntegerField()
    unique_viewers = models.PositiveIntegerField()
    watch_time_sec = models.FloatField()
    videos_watched = models.PositiveIntegerField()
    new_uploads = models.PositiveIntegerField()

    class Meta:
        db_table = "daily_platform_stats"

    def __str__(self):
        return str(self.date)
