from pathlib import Path

from django.conf import settings
from rest_framework import serializers

from apps.orders.serializers import CartSerializer

from .models import ChatMessage, Conversation, KnowledgeDocument, Language

ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}


class ChatRequestSerializer(serializers.Serializer):
    message = serializers.CharField(required=False, allow_blank=True, max_length=settings.AI_MESSAGE_MAX_CHARS)
    image = serializers.ImageField(required=False)
    conversation = serializers.CharField(required=False, allow_blank=True, max_length=64)
    language = serializers.ChoiceField(choices=Language.choices, required=False)

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
    language = serializers.ChoiceField(choices=Language.choices)
    state = serializers.ChoiceField(choices=Conversation.State.choices)
    reply = serializers.CharField()
    products = ChatProductSerializer(many=True)
    cart = CartSerializer(allow_null=True)
    order = ChatOrderSerializer(allow_null=True)
    payment = ChatPaymentSerializer(allow_null=True)
    error = serializers.CharField(allow_null=True)


# --- Admin ---------------------------------------------------------------------------------------

KNOWLEDGE_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}


class KnowledgeDocumentSerializer(serializers.ModelSerializer):
    file = serializers.FileField(write_only=True)
    title = serializers.CharField(max_length=200, required=False, allow_blank=True)

    class Meta:
        model = KnowledgeDocument
        fields = ["id", "title", "language", "status", "error", "chunk_count", "created_at", "indexed_at", "file"]
        read_only_fields = ["status", "error", "chunk_count", "created_at", "indexed_at"]

    def validate_file(self, file):
        suffix = Path(file.name or "").suffix.lower()
        if suffix not in KNOWLEDGE_EXTENSIONS:
            raise serializers.ValidationError("Upload a PDF, DOCX, TXT or MD file.")
        if file.size > settings.AI_UPLOAD_MAX_BYTES:
            limit = settings.AI_UPLOAD_MAX_BYTES // (1024 * 1024)
            raise serializers.ValidationError(f"The file is too large (maximum {limit} MB).")
        return file

    def create(self, validated_data):
        file = validated_data["file"]
        validated_data["title"] = (validated_data.get("title") or "").strip() or Path(file.name).stem[:200]
        validated_data["content_type"] = getattr(file, "content_type", "") or ""
        return super().create(validated_data)


class ReindexRequestSerializer(serializers.Serializer):
    products = serializers.BooleanField(default=True)
    knowledge = serializers.BooleanField(default=True)
    force = serializers.BooleanField(default=False)


class IndexCountsSerializer(serializers.Serializer):
    ready = serializers.IntegerField()
    pending = serializers.IntegerField()
    failed = serializers.IntegerField()


class IndexFailureSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["product", "image", "knowledge"])
    id = serializers.IntegerField()
    name = serializers.CharField()
    error = serializers.CharField()


class IndexStatusSerializer(serializers.Serializer):
    products = IndexCountsSerializer()
    images = IndexCountsSerializer()
    knowledge = IndexCountsSerializer()
    failures = IndexFailureSerializer(many=True)


class AdminMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatMessage
        fields = ["id", "role", "text", "image", "image_deleted", "language", "tool_calls", "payload",
                  "steps", "latency_ms", "error", "created_at"]


class AdminConversationSerializer(serializers.ModelSerializer):
    user = serializers.SlugRelatedField(slug_field="username", read_only=True)
    last_message = serializers.CharField(read_only=True, allow_null=True, default=None)

    class Meta:
        model = Conversation
        fields = ["id", "channel", "state", "language", "handoff_reason", "user", "created_at", "updated_at",
                  "last_message"]


class AdminConversationDetailSerializer(AdminConversationSerializer):
    messages = AdminMessageSerializer(many=True, read_only=True)

    class Meta(AdminConversationSerializer.Meta):
        fields = [*AdminConversationSerializer.Meta.fields, "messages"]
