import logging
import uuid

from botocore.exceptions import BotoCoreError, ClientError
from django.db.models import Q
from pymongo.errors import PyMongoError
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from common.kafka import PublishError
from events.analytics import resume_position
from social.models import Follow

from . import playback, uploads
from .models import Video
from .serializers import CompleteSerializer, VideoCreateSerializer, VideoSerializer

logger = logging.getLogger(__name__)


def analysis_fields(video):
    """The ML worker's public results, on the detail page only. Moderation flags are for reviewers, never shown here."""
    tags = video.tags.filter(kind="topic").values_list("tag", flat=True)
    transcript = getattr(video, "transcript", None)
    subtitles = []
    if transcript and transcript.subtitles_key:
        subtitles.append({"language": transcript.language, "url": playback.cdn_url(transcript.subtitles_key)})
    return {"tags": list(tags), "subtitles": subtitles}


def unavailable():
    return Response({"detail": "Storage or messaging is unavailable. Try again shortly."}, status=503)


class VideoViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """
    GET    /api/videos/              ready videos, public (?mine=true: your own, any status)
    POST   /api/videos/              create + presigned upload URL(s)
    GET    /api/videos/{id}/         details (ready, or yours); ready videos also get CDN cookies + hls_url
    POST   /api/videos/{id}/complete/
    DELETE /api/videos/{id}/         owner only
    """

    serializer_class = VideoSerializer

    def get_permissions(self):
        # Anyone can browse and watch ready videos; everything else needs an account.
        if self.action in ("list", "retrieve") and not self.wants_mine():
            return [AllowAny()]
        return [IsAuthenticated()]

    def wants_mine(self):
        return self.request.query_params.get("mine") in ("1", "true")

    def get_queryset(self):
        qs = Video.objects.select_related("owner").prefetch_related("renditions")
        user = self.request.user
        ready = Q(status=Video.Status.READY)
        if self.action == "list":
            return qs.filter(owner=user) if self.wants_mine() else qs.filter(ready)
        return qs.filter(ready | Q(owner=user)) if user.is_authenticated else qs.filter(ready)

    def retrieve(self, request, pk=None):
        video = self.get_object()
        response = Response(VideoSerializer(video, context={"request": request}).data)
        if video.status == Video.Status.READY:
            response.data["playback"] = playback.grant_playback(response, video)
        response.data.update(analysis_fields(video))
        user = request.user
        if user.is_authenticated:
            response.data["is_following"] = Follow.objects.filter(follower=user, followee_id=video.owner_id).exists()
            if video.status == Video.Status.READY:
                try:
                    response.data["resume_position_sec"] = resume_position(user.id, video)
                except PyMongoError:
                    logger.warning("watch progress unavailable for video %s", video.id)  # play from the start
        return response

    def get_throttles(self):
        self.throttle_scope = "upload" if self.action == "create" else None
        return super().get_throttles()

    def get_owned_object(self):
        video = self.get_object()
        if video.owner_id != self.request.user.id:
            raise NotFound()
        return video

    def create(self, request):
        serializer = VideoCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        video_id = uuid.uuid4()
        video = Video.objects.create(
            id=video_id,
            owner=request.user,
            title=data["title"],
            description=data["description"],
            original_filename=data["filename"],
            content_type=data["content_type"],
            size_bytes=data["size"],
            source_key=uploads.source_key_for(video_id, data["extension"]),
        )
        try:
            upload = uploads.start_upload(video)
        except (BotoCoreError, ClientError):
            logger.exception("Could not start upload for video %s", video.id)
            video.delete()
            return unavailable()
        return Response(
            {"video": VideoSerializer(video, context={"request": request}).data, "upload": upload},
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        video = self.get_owned_object()
        serializer = CompleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            video = uploads.complete_upload(video.pk, serializer.validated_data.get("parts"))
        except (BotoCoreError, ClientError, PublishError):
            logger.exception("Could not complete upload for video %s", video.pk)
            return unavailable()
        return Response(VideoSerializer(video, context={"request": request}).data)

    def destroy(self, request, pk=None):
        video = self.get_owned_object()
        try:
            uploads.delete_video(video)
        except (BotoCoreError, ClientError):
            logger.exception("Could not delete storage for video %s", video.pk)
            return unavailable()
        return Response(status=status.HTTP_204_NO_CONTENT)
