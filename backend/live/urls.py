from django.urls import path

from .views import LiveOverviewView, VideoLiveView

urlpatterns = [
    path("live/", LiveOverviewView.as_view(), name="live-overview"),
    path("videos/<uuid:video_id>/live/", VideoLiveView.as_view(), name="video-live"),
]
