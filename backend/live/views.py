import uuid

from django.shortcuts import get_object_or_404
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from recommendations.views import _ready_videos
from videos.models import Video

from . import metrics

TRENDING_LIMIT = 8


def _as_uuids(values):
    """Redis holds text, and these come from client events: an id that isn't a UUID simply isn't a video."""
    ids = []
    for value in values:
        try:
            ids.append(uuid.UUID(value))
        except ValueError:
            continue
    return ids


class LiveOverviewView(APIView):
    """GET /api/live/: people watching now and the last hour's trending. available=false if the stream isn't running."""

    permission_classes = [AllowAny]

    def get(self, request):
        snapshot = metrics.snapshot(trending_limit=TRENDING_LIMIT * 2)  # some may have been deleted since
        if snapshot is None:
            return Response({"available": False, "viewers_now": 0, "trending": []})
        return Response(
            {
                "available": True,
                "updated_at": snapshot["updated_at"],
                "viewers_now": sum(snapshot["viewers"].values()),
                "trending": _ready_videos(_as_uuids(snapshot["trending"]), TRENDING_LIMIT, request),
            }
        )


class VideoLiveView(APIView):
    """GET /api/videos/{id}/live/: people watching this video now."""

    permission_classes = [AllowAny]

    def get(self, request, video_id):
        get_object_or_404(Video, pk=video_id, status=Video.Status.READY)
        snapshot = metrics.snapshot(trending_limit=1)
        if snapshot is None:
            return Response({"available": False, "viewers": 0})
        return Response({"available": True, "viewers": snapshot["viewers"].get(str(video_id), 0)})
