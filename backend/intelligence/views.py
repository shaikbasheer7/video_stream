from django.contrib.postgres.aggregates import StringAgg
from django.contrib.postgres.search import SearchHeadline, SearchQuery, SearchRank, SearchVector
from django.db.models import OuterRef, Subquery, TextField
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from videos.models import Video
from videos.serializers import VideoSerializer

from .models import VideoTag

CONFIG = "english"
MAX_RESULTS = 30
MAX_QUERY_LENGTH = 200
# Plain markers, not HTML: the browser renders the highlight itself, so a transcript can't inject markup.
MARK_START, MARK_END = "[[", "]]"


class SearchView(APIView):
    """GET /api/search/?q=...: ready videos by title, description, tags and what is said in them.

    Basic PostgreSQL full-text search (blueprint): the document is built per query, which is fine for an MVP
    catalogue. A stored tsvector with a GIN index, then OpenSearch, are the next steps as the catalogue grows.
    """

    permission_classes = [AllowAny]
    throttle_scope = "search"

    def get(self, request):
        text = request.query_params.get("q", "").strip()[:MAX_QUERY_LENGTH]
        if len(text) < 2:
            return Response({"query": text, "results": []})

        query = SearchQuery(text, search_type="websearch", config=CONFIG)
        topic_tags = (
            VideoTag.objects.filter(video=OuterRef("pk"), kind=VideoTag.Kind.TOPIC)
            .order_by()
            .values("video")
            .annotate(all_tags=StringAgg("tag", " "))
            .values("all_tags")
        )
        document = (
            SearchVector("title", weight="A", config=CONFIG)
            + SearchVector("description", weight="B", config=CONFIG)
            + SearchVector(Subquery(topic_tags, output_field=TextField()), weight="C", config=CONFIG)
            + SearchVector("transcript__text", weight="D", config=CONFIG)
        )
        videos = (
            Video.objects.filter(status=Video.Status.READY)
            .annotate(document=document)
            .filter(document=query)
            .annotate(
                rank=SearchRank(document, query),
                snippet=SearchHeadline(
                    "transcript__text",
                    query,
                    config=CONFIG,
                    start_sel=MARK_START,
                    stop_sel=MARK_END,
                    max_words=30,
                    min_words=12,
                ),
            )
            .select_related("owner")
            .prefetch_related("renditions")
            .order_by("-rank", "-created_at")[:MAX_RESULTS]
        )
        results = []
        for video in videos:
            item = VideoSerializer(video, context={"request": request}).data
            # Only when the words were actually said; otherwise it would just be the transcript's opening.
            item["snippet"] = video.snippet if video.snippet and MARK_START in video.snippet else None
            results.append(item)
        return Response({"query": text, "results": results})
