from rest_framework import serializers

from .models import Category, Product, ProductImage


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name", "name_sw", "slug", "parent", "is_active"]
        read_only_fields = ["slug"]


class ProductImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductImage
        fields = ["id", "image", "alt_text", "position"]


class ProductSerializer(serializers.ModelSerializer):
    images = ProductImageSerializer(many=True, read_only=True)
    category_name = serializers.CharField(source="category.name", read_only=True, default=None)
    in_stock = serializers.BooleanField(read_only=True)
    uploaded_images = serializers.ListField(
        child=serializers.ImageField(), write_only=True, required=False
    )

    class Meta:
        model = Product
        fields = [
            "id", "name", "slug", "sku", "category", "category_name",
            "description", "description_sw", "price", "compare_at_price",
            "stock", "low_stock_threshold", "in_stock", "attributes", "tags",
            "is_active", "images", "uploaded_images", "created_at", "updated_at",
        ]
        read_only_fields = ["slug", "created_at", "updated_at"]

    def validate_price(self, value):
        if value <= 0:
            raise serializers.ValidationError("Price must be greater than zero.")
        return value

    def _save_images(self, product, images):
        start = product.images.count()
        for i, img in enumerate(images):
            ProductImage.objects.create(product=product, image=img, position=start + i)

    def create(self, validated_data):
        images = validated_data.pop("uploaded_images", [])
        product = super().create(validated_data)
        self._save_images(product, images)
        return product

    def update(self, instance, validated_data):
        images = validated_data.pop("uploaded_images", [])
        product = super().update(instance, validated_data)
        self._save_images(product, images)
        return product


class PublicProductSerializer(ProductSerializer):
    """Storefront view: hides inventory internals."""

    class Meta(ProductSerializer.Meta):
        fields = [
            f for f in ProductSerializer.Meta.fields
            if f not in {"low_stock_threshold", "uploaded_images", "is_active", "stock"}
        ]
