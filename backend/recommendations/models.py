"""Precomputed by the nightly pipeline (data/pipeline); the API only reads them.

Ids are plain columns, not foreign keys: the pipeline replaces these tables wholesale, and the API filters out
videos that were deleted or unpublished since the last run.
"""

from django.db import models


class VideoEmbedding(models.Model):
    """Reused between runs until the video's text or the model changes."""

    video_id = models.UUIDField(primary_key=True)
    text_hash = models.CharField(max_length=64)
    model = models.CharField(max_length=100)
    vector = models.JSONField()
    updated_at = models.DateTimeField()

    class Meta:
        db_table = "video_embeddings"

    def __str__(self):
        return str(self.video_id)


class RankedVideo(models.Model):
    """The trending and popular lists."""

    class List(models.TextChoices):
        TRENDING = "trending"
        POPULAR = "popular"

    list_name = models.CharField(max_length=20, choices=List.choices)
    rank = models.PositiveSmallIntegerField()
    video_id = models.UUIDField()
    score = models.FloatField()
    generated_at = models.DateTimeField()

    class Meta:
        db_table = "ranked_videos"
        ordering = ["list_name", "rank"]
        constraints = [models.UniqueConstraint(fields=["list_name", "rank"], name="unique_list_rank")]

    def __str__(self):
        return f"{self.list_name} #{self.rank}"


class SimilarVideo(models.Model):
    video_id = models.UUIDField()
    similar_video_id = models.UUIDField()
    rank = models.PositiveSmallIntegerField()
    score = models.FloatField()
    model_version = models.CharField(max_length=50)
    generated_at = models.DateTimeField()

    class Meta:
        db_table = "similar_videos"
        ordering = ["video_id", "rank"]
        constraints = [models.UniqueConstraint(fields=["video_id", "rank"], name="unique_similar_rank")]

    def __str__(self):
        return f"{self.video_id} #{self.rank}"


class Recommendation(models.Model):
    user_id = models.BigIntegerField()
    video_id = models.UUIDField()
    rank = models.PositiveSmallIntegerField()
    score = models.FloatField()
    model_version = models.CharField(max_length=50)
    generated_at = models.DateTimeField()

    class Meta:
        db_table = "recommendations"
        ordering = ["user_id", "rank"]
        constraints = [models.UniqueConstraint(fields=["user_id", "rank"], name="unique_user_rank")]

    def __str__(self):
        return f"{self.user_id} #{self.rank}"
