from django.conf import settings
from rest_framework import serializers

from apps.orders.serializers import CartSerializer

ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}


class ChatRequestSerializer(serializers.Serializer):
    message = serializers.CharField(required=False, allow_blank=True, max_length=settings.AI_MESSAGE_MAX_CHARS)
    image = serializers.ImageField(required=False)
    conversation = serializers.CharField(required=False, allow_blank=True, max_length=64)
    language = serializers.ChoiceField(choices=["sw", "en"], required=False)

    def validate_image(self, image):
        if image.size > settings.AI_UPLOAD_MAX_BYTES:
            limit = settings.AI_UPLOAD_MAX_BYTES // (1024 * 1024)
            raise serializers.ValidationError(f"The photo is too large (maximum {limit} MB).")
        fmt = getattr(getattr(image, "image", None), "format", None)
        if fmt not in ALLOWED_IMAGE_FORMATS:
            raise serializers.ValidationError("Please send a JPEG, PNG or WebP photo.")
        image.seek(0)
        return image

    def validate(self, data):
        if not (data.get("message") or "").strip() and not data.get("image"):
            raise serializers.ValidationError({"message": "Send a message or a photo."})
        return data


class ChatProductSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    slug = serializers.CharField()
    price = serializers.DecimalField(max_digits=12, decimal_places=2)
    compare_at_price = serializers.DecimalField(max_digits=12, decimal_places=2, allow_null=True)
    in_stock = serializers.BooleanField()
    image = serializers.CharField(allow_null=True)
    category_name = serializers.CharField(allow_null=True)


class ChatOrderSerializer(serializers.Serializer):
    number = serializers.CharField()
    status = serializers.CharField()
    total = serializers.DecimalField(max_digits=12, decimal_places=2)
    currency = serializers.CharField()


class ChatPaymentSerializer(serializers.Serializer):
    method = serializers.CharField()
    status = serializers.CharField()
    checkout_link = serializers.CharField(allow_blank=True)
    message = serializers.CharField(allow_blank=True)


class ChatResponseSerializer(serializers.Serializer):
    conversation_token = serializers.CharField()
    cart_token = serializers.CharField(allow_null=True)
    language = serializers.ChoiceField(choices=["sw", "en"])
    state = serializers.ChoiceField(choices=["active", "needs_human"])
    reply = serializers.CharField()
    products = ChatProductSerializer(many=True)
    cart = CartSerializer(allow_null=True)
    order = ChatOrderSerializer(allow_null=True)
    payment = ChatPaymentSerializer(allow_null=True)
    error = serializers.CharField(allow_null=True)
