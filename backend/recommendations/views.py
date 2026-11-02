from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from videos.models import Video
from videos.serializers import VideoSerializer

from .models import RankedVideo, Recommendation, SimilarVideo

DEFAULT_LIMIT = 12
MAX_LIMIT = 50


def _limit(request):
    try:
        return max(1, min(int(request.query_params.get("limit", DEFAULT_LIMIT)), MAX_LIMIT))
    except ValueError:
        return DEFAULT_LIMIT


def _ready_videos(ids, limit, request):
    """Serialize in the given order. Lists are precomputed, so videos deleted since then simply drop out."""
    videos = Video.objects.filter(pk__in=ids, status=Video.Status.READY).select_related("owner")
    by_id = {v.id: v for v in videos.prefetch_related("renditions")}
    ordered = [by_id[i] for i in ids if i in by_id][:limit]
    return VideoSerializer(ordered, many=True, context={"request": request}).data


def _ranked(list_name, limit, request):
    ids = list(RankedVideo.objects.filter(list_name=list_name).order_by("rank").values_list("video_id", flat=True))
    return _ready_videos(ids, limit, request)


def _latest(limit, request):
    ids = list(
        Video.objects.filter(status=Video.Status.READY).order_by("-created_at").values_list("id", flat=True)[:limit]
    )
    return _ready_videos(ids, limit, request)


@api_view(["GET"])
@permission_classes([AllowAny])
def recommendations(request):
    """Personalised picks when we have them, else trending, else the newest videos (a new site has no stats)."""
    limit = _limit(request)
    if request.user.is_authenticated:
        ids = list(
            Recommendation.objects.filter(user_id=request.user.id).order_by("rank").values_list("video_id", flat=True)
        )
        results = _ready_videos(ids, limit, request)
        if results:
            return Response({"source": "personalized", "results": results})
    results = _ranked(RankedVideo.List.TRENDING, limit, request)
    if results:
        return Response({"source": "trending", "results": results})
    return Response({"source": "latest", "results": _latest(limit, request)})


@api_view(["GET"])
@permission_classes([AllowAny])
def trending(request):
    return Response({"results": _ranked(RankedVideo.List.TRENDING, _limit(request), request)})


@api_view(["GET"])
@permission_classes([AllowAny])
def popular(request):
    return Response({"results": _ranked(RankedVideo.List.POPULAR, _limit(request), request)})


@api_view(["GET"])
@permission_classes([AllowAny])
def similar(request, video_id):
    """Videos like this one. A video too new to have an embedding yet gets trending videos instead."""
    get_object_or_404(Video, pk=video_id, status=Video.Status.READY)
    limit = _limit(request)
    ids = list(
        SimilarVideo.objects.filter(video_id=video_id).order_by("rank").values_list("similar_video_id", flat=True)
    )
    results = _ready_videos(ids, limit, request)
    if results:
        return Response({"source": "similar", "results": results})
    # Over-fetch by one so that removing this video still leaves a full list.
    fallback = [v for v in _ranked(RankedVideo.List.TRENDING, limit + 1, request) if v["id"] != str(video_id)]
    return Response({"source": "trending", "results": fallback[:limit]})
