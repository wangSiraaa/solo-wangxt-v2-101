from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    BoundVolumeViewSet, IssueViewSet, LocateView, PieceViewSet,
    SerialViewSet,
)

router = DefaultRouter()
router.register("serials", SerialViewSet, basename="serial")
router.register("issues", IssueViewSet, basename="issue")
router.register("pieces", PieceViewSet, basename="piece")
router.register("bound-volumes", BoundVolumeViewSet, basename="boundvolume")

urlpatterns = [
    path("", include(router.urls)),
    path("locate/", LocateView.as_view(), name="locate"),
]
