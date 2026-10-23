from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import CategoryViewSet, ProductImageViewSet, ProductViewSet

router = DefaultRouter()
router.register("categories", CategoryViewSet, basename="category")
router.register("products", ProductViewSet, basename="product")

image_list = ProductImageViewSet.as_view({"get": "list", "post": "create"})
image_detail = ProductImageViewSet.as_view({"patch": "partial_update", "delete": "destroy"})

urlpatterns = router.urls + [
    path("products/<slug:product_slug>/images/", image_list),
    path("products/<slug:product_slug>/images/<int:pk>/", image_detail),
]
