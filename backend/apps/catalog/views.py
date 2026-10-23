from django_filters import rest_framework as filters
from rest_framework import parsers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.permissions import IsShopAdmin, IsShopAdminOrReadOnly

from .models import Category, Product, ProductImage
from .serializers import (
    CategorySerializer,
    ProductImageSerializer,
    ProductSerializer,
    PublicProductSerializer,
)


class ProductFilter(filters.FilterSet):
    min_price = filters.NumberFilter(field_name="price", lookup_expr="gte")
    max_price = filters.NumberFilter(field_name="price", lookup_expr="lte")
    category = filters.CharFilter(field_name="category__slug")
    in_stock = filters.BooleanFilter(method="filter_in_stock")

    class Meta:
        model = Product
        fields = ["category", "is_active"]

    def filter_in_stock(self, queryset, name, value):
        return queryset.filter(stock__gt=0) if value else queryset.filter(stock=0)


class CategoryViewSet(viewsets.ModelViewSet):
    serializer_class = CategorySerializer
    permission_classes = [IsShopAdminOrReadOnly]
    lookup_field = "slug"

    def get_queryset(self):
        qs = Category.objects.all()
        user = self.request.user
        if not (user.is_authenticated and user.is_shop_admin):
            qs = qs.filter(is_active=True)
        return qs


class ProductViewSet(viewsets.ModelViewSet):
    """Public read access to active products; admins get full CRUD and see inactive items."""

    permission_classes = [IsShopAdminOrReadOnly]
    parser_classes = [parsers.JSONParser, parsers.MultiPartParser, parsers.FormParser]
    filterset_class = ProductFilter
    search_fields = ["name", "description", "description_sw", "tags", "sku", "category__name"]
    ordering_fields = ["price", "created_at", "name", "stock"]
    lookup_field = "slug"

    def _is_admin(self):
        user = self.request.user
        return user.is_authenticated and user.is_shop_admin

    def get_queryset(self):
        qs = Product.objects.select_related("category").prefetch_related("images")
        if not self._is_admin():
            qs = qs.filter(is_active=True)
        return qs

    def get_serializer_class(self):
        return ProductSerializer if self._is_admin() else PublicProductSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=False, permission_classes=[IsShopAdmin])
    def low_stock(self, request):
        from django.db.models import F

        qs = self.get_queryset().filter(is_active=True, stock__lte=F("low_stock_threshold"))
        return Response(ProductSerializer(qs, many=True, context={"request": request}).data)


class ProductImageViewSet(viewsets.ModelViewSet):
    serializer_class = ProductImageSerializer
    permission_classes = [IsShopAdmin]
    parser_classes = [parsers.MultiPartParser, parsers.FormParser, parsers.JSONParser]

    def get_queryset(self):
        return ProductImage.objects.filter(product__slug=self.kwargs["product_slug"])

    def perform_create(self, serializer):
        product = Product.objects.get(slug=self.kwargs["product_slug"])
        serializer.save(product=product)
