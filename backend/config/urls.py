from django.contrib import admin
from django.urls import include, path

from common.views import health, ready

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include("accounts.urls")),
    path("api/health/", health, name="health"),
    path("api/health/ready/", ready, name="health-ready"),
    path("api/", include("videos.urls")),
    path("api/", include("events.urls")),
    path("api/", include("notifications.urls")),
    path("api/", include("social.urls")),
    path("api/", include("recommendations.urls")),
    path("api/", include("intelligence.urls")),
    path("api/", include("live.urls")),
]
