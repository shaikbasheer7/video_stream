from django.contrib import admin

from .models import VideoTag


@admin.register(VideoTag)
class VideoTagAdmin(admin.ModelAdmin):
    """Filter by kind = moderation for the review queue."""

    list_display = ["video", "kind", "tag", "confidence", "source"]
    list_filter = ["kind", "source", "tag"]
    search_fields = ["video__title", "tag"]
    raw_id_fields = ["video"]
