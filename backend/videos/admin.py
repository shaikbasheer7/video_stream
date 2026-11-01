from django.contrib import admin

from .models import Rendition, Video


class RenditionInline(admin.TabularInline):
    model = Rendition
    extra = 0


@admin.register(Video)
class VideoAdmin(admin.ModelAdmin):
    list_display = ["title", "owner", "status", "size_bytes", "duration_sec", "created_at"]
    list_filter = ["status"]
    search_fields = ["title", "owner__email", "id"]
    readonly_fields = ["id", "source_key", "upload_id", "created_at", "updated_at"]
    inlines = [RenditionInline]
