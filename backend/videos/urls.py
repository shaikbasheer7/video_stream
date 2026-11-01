from rest_framework.routers import DefaultRouter

from .views import VideoViewSet

router = DefaultRouter()
router.register("videos", VideoViewSet, basename="video")

urlpatterns = router.urls
