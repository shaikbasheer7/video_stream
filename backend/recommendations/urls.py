from django.urls import path

from . import views

urlpatterns = [
    path("recommendations/", views.recommendations, name="recommendations"),
    path("recommendations/trending/", views.trending, name="trending"),
    path("recommendations/popular/", views.popular, name="popular"),
    path("videos/<uuid:video_id>/similar/", views.similar, name="similar-videos"),
]
