from rest_framework import generics, permissions, viewsets
from rest_framework_simplejwt.views import TokenObtainPairView

from .models import RiderProfile
from .permissions import IsShopAdmin
from .serializers import (
    AddressSerializer,
    RegisterSerializer,
    RiderSerializer,
    ShopTokenObtainPairSerializer,
    UserSerializer,
)


class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]


class LoginView(TokenObtainPairView):
    serializer_class = ShopTokenObtainPairSerializer


class MeView(generics.RetrieveUpdateAPIView):
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user


class AddressViewSet(viewsets.ModelViewSet):
    serializer_class = AddressSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return self.request.user.addresses.all()

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class RiderViewSet(viewsets.ModelViewSet):
    serializer_class = RiderSerializer
    permission_classes = [IsShopAdmin]
    queryset = RiderProfile.objects.select_related("user").order_by("-created_at")
    filterset_fields = ["is_available", "zone", "vehicle"]
    search_fields = ["user__first_name", "user__last_name", "user__phone", "plate_number"]
