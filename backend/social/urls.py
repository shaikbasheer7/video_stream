from django.urls import path

from .views import FeedView, FollowView

urlpatterns = [
    path("users/<int:user_id>/follow/", FollowView.as_view(), name="follow"),
    path("feed/", FeedView.as_view(), name="feed"),
]
