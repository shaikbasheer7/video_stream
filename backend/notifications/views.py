from rest_framework.response import Response
from rest_framework.views import APIView

from common import mongo

PAGE = 30


def serialize(doc):
    return {
        "id": doc["_id"],
        "type": doc["type"],
        "video_id": doc["video_id"],
        "title": doc["title"],
        "error": doc.get("error", ""),
        "read": doc["read"],
        "created_at": doc["created_at"].isoformat(),
    }


class NotificationListView(APIView):
    """GET /api/notifications/: the latest notifications and the unread count."""

    def get(self, request):
        collection = mongo.db().notifications
        docs = collection.find({"user_id": request.user.id}).sort("created_at", -1).limit(PAGE)
        return Response(
            {
                "unread": collection.count_documents({"user_id": request.user.id, "read": False}),
                "results": [serialize(d) for d in docs],
            }
        )


class NotificationReadView(APIView):
    """POST /api/notifications/read/: mark all as read."""

    def post(self, request):
        mongo.db().notifications.update_many({"user_id": request.user.id, "read": False}, {"$set": {"read": True}})
        return Response(status=204)
