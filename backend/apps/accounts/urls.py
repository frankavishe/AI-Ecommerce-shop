from django.urls import path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from .views import AddressViewSet, LoginView, MeView, RegisterView, RiderViewSet

router = DefaultRouter()
router.register("addresses", AddressViewSet, basename="address")
router.register("riders", RiderViewSet, basename="rider")

urlpatterns = [
    path("register/", RegisterView.as_view()),
    path("login/", LoginView.as_view()),
    path("refresh/", TokenRefreshView.as_view()),
    path("me/", MeView.as_view()),
] + router.urls
