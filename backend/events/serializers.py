from rest_framework import serializers

EVENT_TYPES = ["play", "pause", "seek", "progress", "quality_change", "buffering", "complete"]
MAX_SECONDS = 24 * 3600


class PlaybackEventSerializer(serializers.Serializer):
    type = serializers.ChoiceField(EVENT_TYPES)
    video_id = serializers.UUIDField()
    session_id = serializers.CharField(max_length=64)
    ts = serializers.DateTimeField()  # client clock
    position_sec = serializers.FloatField(min_value=0, max_value=MAX_SECONDS)
    quality = serializers.CharField(max_length=10, required=False, allow_blank=True, allow_null=True)
    # Type-specific fields (blueprint section 12.1).
    from_sec = serializers.FloatField(min_value=0, max_value=MAX_SECONDS, required=False)  # seek
    to_sec = serializers.FloatField(min_value=0, max_value=MAX_SECONDS, required=False)  # seek
    from_quality = serializers.CharField(max_length=10, required=False, allow_blank=True)  # quality_change
    to_quality = serializers.CharField(max_length=10, required=False, allow_blank=True)  # quality_change
    auto = serializers.BooleanField(required=False)  # quality_change
    duration_ms = serializers.IntegerField(min_value=0, max_value=3_600_000, required=False)  # buffering
    watch_time_sec = serializers.FloatField(min_value=0, max_value=MAX_SECONDS, required=False)  # complete

    def validate(self, attrs):
        if attrs["type"] == "seek" and ("from_sec" not in attrs or "to_sec" not in attrs):
            raise serializers.ValidationError("seek needs from_sec and to_sec")
        return attrs


class EventBatchSerializer(serializers.Serializer):
    anonymous_id = serializers.CharField(max_length=64)  # stable per browser, for logged-out viewers
    events = PlaybackEventSerializer(many=True, allow_empty=False, max_length=100)
