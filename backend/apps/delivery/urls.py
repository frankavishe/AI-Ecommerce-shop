from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter(trailing_slash=True)
router.include_root_view = False
router.register("admin/deliveries", views.AdminDeliveryViewSet, basename="admin-delivery")

urlpatterns = router.urls + [
    path("admin/orders/<str:number>/delivery/", views.CreateDeliveryView.as_view()),
]
