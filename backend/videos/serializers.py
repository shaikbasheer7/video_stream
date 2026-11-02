from django.conf import settings
from rest_framework import serializers

from .models import Rendition, Video
from .playback import cdn_url
from .uploads import ALLOWED_TYPES


class RenditionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Rendition
        fields = ["quality", "width", "height", "bitrate_kbps"]


class VideoSerializer(serializers.ModelSerializer):
    owner = serializers.SerializerMethodField()
    is_owner = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()
    renditions = RenditionSerializer(many=True, read_only=True)

    class Meta:
        model = Video
        fields = [
            "id",
            "title",
            "description",
            "status",
            "owner",
            "owner_id",
            "is_owner",
            "original_filename",
            "size_bytes",
            "duration_sec",
            "width",
            "height",
            "error_message",
            "thumbnail_url",
            "renditions",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_owner(self, video):
        return video.owner.display_name or video.owner.email.split("@")[0]

    def get_thumbnail_url(self, video):
        # Thumbnails are public through the CDN; only /hls/ needs signed cookies.
        return cdn_url(video.thumbnail_key) if video.thumbnail_key else None

    def get_is_owner(self, video):
        request = self.context.get("request")
        return bool(request and request.user.id == video.owner_id)


class VideoCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    description = serializers.CharField(allow_blank=True, required=False, default="")
    filename = serializers.CharField(max_length=255)
    size = serializers.IntegerField(min_value=1)
    content_type = serializers.CharField(max_length=100)

    def validate(self, attrs):
        name, _, extension = attrs["filename"].rpartition(".")
        extension = extension.lower()
        if not name or extension not in ALLOWED_TYPES:
            raise serializers.ValidationError({"filename": f"Allowed formats: {', '.join(sorted(ALLOWED_TYPES))}."})
        if attrs["content_type"] not in ALLOWED_TYPES[extension]:
            raise serializers.ValidationError({"content_type": f"Content type does not match a .{extension} file."})
        if attrs["size"] > settings.MAX_UPLOAD_BYTES:
            limit_gb = settings.MAX_UPLOAD_BYTES / 1024**3
            raise serializers.ValidationError({"size": f"Files are limited to {limit_gb:g} GB."})
        attrs["extension"] = extension
        return attrs


class PartSerializer(serializers.Serializer):
    part_number = serializers.IntegerField(min_value=1, max_value=10_000)
    etag = serializers.CharField(max_length=200)


class CompleteSerializer(serializers.Serializer):
    parts = PartSerializer(many=True, required=False)
