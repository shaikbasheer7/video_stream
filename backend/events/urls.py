from django.urls import path

from .views import EventBatchView

urlpatterns = [path("events/batch/", EventBatchView.as_view(), name="event-batch")]
