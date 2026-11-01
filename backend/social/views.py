from django.db import IntegrityError
from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from common import mongo
from videos.models import Video
from videos.serializers import VideoSerializer

from .models import Follow

FEED_LIMIT = 50


class FollowView(APIView):
    """POST / DELETE /api/users/{id}/follow/"""

    def post(self, request, user_id):
        followee = get_object_or_404(User, pk=user_id, is_active=True)
        if followee.id == request.user.id:
            return Response({"detail": "You can't follow yourself."}, status=400)
        try:
            Follow.objects.get_or_create(follower=request.user, followee=followee)
        except IntegrityError:
            pass  # concurrent duplicate
        return Response({"following": True, "followers": followee.followers.count()})

    def delete(self, request, user_id):
        followee = get_object_or_404(User, pk=user_id)
        Follow.objects.filter(follower=request.user, followee=followee).delete()
        return Response({"following": False, "followers": followee.followers.count()})


class FeedView(APIView):
    """GET /api/feed/: newest ready videos from creators you follow."""

    def get(self, request):
        items = list(mongo.db().feed_items.find({"user_id": request.user.id}).sort("created_at", -1).limit(FEED_LIMIT))
        order = {item["video_id"]: i for i, item in enumerate(items)}
        videos = (
            Video.objects.filter(pk__in=order.keys(), status=Video.Status.READY)
            .select_related("owner")
            .prefetch_related("renditions")
        )
        ordered = sorted(videos, key=lambda v: order[str(v.id)])  # deleted videos simply drop out
        return Response({"results": VideoSerializer(ordered, many=True, context={"request": request}).data})
