import re
from datetime import UTC, datetime

from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken

from common import geo, kafka

from .serializers import EventBatchSerializer

MOBILE = re.compile(r"Mobi|Android|iPhone", re.I)
TABLET = re.compile(r"iPad|Tablet", re.I)


def device_from_user_agent(ua):
    if TABLET.search(ua or ""):
        return "tablet"
    if MOBILE.search(ua or ""):
        return "mobile"
    return "desktop"


def country_from_request(request):
    # nginx always overwrites X-Real-IP, so a client can't fake it. Only the country is kept, never the address.
    return geo.country_for_ip(request.headers.get("X-Real-IP") or request.META.get("REMOTE_ADDR"))


class OptionalJWTAuthentication(JWTAuthentication):
    """The final flush on page hide (?final=1) can't refresh an expired token first.
    Record those events anonymously instead of losing them; normal flushes still get a 401 and refresh."""

    def authenticate(self, request):
        try:
            return super().authenticate(request)
        except (InvalidToken, AuthenticationFailed):
            if request.query_params.get("final") == "1":
                return None
            raise


class EventBatchView(APIView):
    """POST /api/events/batch/: validate and publish to events.playback. Never writes a database here."""

    authentication_classes = [OptionalJWTAuthentication]
    permission_classes = [AllowAny]
    throttle_scope = "events"

    def get_authenticate_header(self, request):
        return 'Bearer realm="api"'

    def post(self, request):
        serializer = EventBatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        context = {
            "user_id": request.user.id if request.user.is_authenticated else None,
            "anonymous_id": serializer.validated_data["anonymous_id"],
            "device": device_from_user_agent(request.headers.get("User-Agent")),
            "country": country_from_request(request),
            "received_at": datetime.now(UTC).isoformat(),
        }
        messages = []
        for event in serializer.validated_data["events"]:
            event = dict(event)
            client_ts = event.pop("ts")
            video_id = str(event.pop("video_id"))
            payload = {**context, **event, "video_id": video_id, "client_ts": client_ts.isoformat()}
            messages.append((video_id, payload))  # keyed by video_id: one video's events stay ordered
        try:
            kafka.publish_many(kafka.EVENTS_PLAYBACK, messages, event="playback")
        except kafka.PublishError:
            return Response({"detail": "Event intake is temporarily unavailable."}, status=503)
        return Response({"accepted": len(messages)}, status=status.HTTP_202_ACCEPTED)
