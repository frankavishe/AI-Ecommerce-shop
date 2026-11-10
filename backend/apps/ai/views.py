from django.db import transaction
from django.db.models import Count, OuterRef, Subquery
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.accounts.permissions import IsShopAdmin
from apps.catalog.models import Product, ProductImage
from apps.orders.models import Cart
from apps.orders.services import GUEST_CART_LIFETIME, merge_carts

from . import agent, tasks
from .models import ChatMessage, Conversation, IndexStatus, KnowledgeDocument, ProductImageIndex, ProductIndex
from .serializers import (
    AdminConversationDetailSerializer, AdminConversationSerializer, ChatRequestSerializer, ChatResponseSerializer,
    IndexStatusSerializer, KnowledgeDocumentSerializer, ReindexRequestSerializer,
)
from .throttles import ConversationRateThrottle

NOT_FOUND = "Conversation not found."


def resolve_conversation(request, token):
    """Research R8: a guest proves ownership with the token; a customer's conversation is theirs only."""
    user = request.user if request.user.is_authenticated else None
    if not token:
        conversation = Conversation(user=user)
        if user is None:
            conversation.cart = Cart.objects.create()
        conversation.save()
        return conversation

    conversation = Conversation.objects.filter(
        token=token, updated_at__gte=timezone.now() - GUEST_CART_LIFETIME
    ).select_related("cart").first()
    if conversation is None:
        raise NotFound(NOT_FOUND)
    if conversation.user_id is not None:
        if user is None or conversation.user_id != user.pk:
            raise NotFound(NOT_FOUND)
        return conversation
    if user is not None:  # a guest who logged in claims the chat, and its cart joins theirs
        if conversation.cart is not None:
            merge_carts(Cart.objects.get_or_create(user=user)[0], conversation.cart)
        conversation.user = user
        conversation.cart = None
        conversation.save(update_fields=["user", "cart", "updated_at"])
    return conversation


def guest_cart_token(conversation):
    if conversation.user_id is not None:
        return None
    if conversation.cart is None:
        conversation.cart = Cart.objects.create()
        conversation.save(update_fields=["cart", "updated_at"])
    return conversation.cart.token


class ChatView(APIView):
    """Send one message (text and/or photo) to the shopping assistant."""

    parser_classes = [JSONParser, MultiPartParser, FormParser]
    throttle_classes = [ScopedRateThrottle, ConversationRateThrottle]
    throttle_scope = "ai_chat"

    @extend_schema(request={"application/json": ChatRequestSerializer,
                            "multipart/form-data": ChatRequestSerializer},
                   responses=ChatResponseSerializer)
    def post(self, request):
        data = ChatRequestSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        conversation = resolve_conversation(request, data.validated_data.get("conversation"))
        reply = agent.handle_message(
            conversation,
            text=data.validated_data.get("message", ""),
            image=data.validated_data.get("image"),
            user=request.user,
            language=data.validated_data.get("language"),
        )
        conversation.refresh_from_db(fields=["state", "language", "cart"])
        cart_token = guest_cart_token(conversation)  # after the turn: a tool may have replaced an expired cart
        return Response({
            "conversation_token": conversation.token,
            "cart_token": cart_token,
            "language": conversation.language,
            "state": conversation.state,
            "reply": reply.text,
            **reply.payload,
            "error": reply.error or None,
        })


# --- Admin (specs/003-ai-core/contracts/chat-api.md) --------------------------------------------


def _queue(task, *args, **kwargs):
    transaction.on_commit(lambda: task.delay(*args, **kwargs))


class KnowledgeDocumentViewSet(mixins.ListModelMixin, mixins.CreateModelMixin, mixins.RetrieveModelMixin,
                               mixins.DestroyModelMixin, viewsets.GenericViewSet):
    """Shop policy and help documents the assistant answers from."""

    queryset = KnowledgeDocument.objects.all()
    serializer_class = KnowledgeDocumentSerializer
    permission_classes = [IsShopAdmin]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def perform_create(self, serializer):
        document = serializer.save(uploaded_by=self.request.user)
        _queue(tasks.index_document, document.pk)

    def perform_destroy(self, instance):
        instance.file.delete(save=False)
        instance.delete()

    @extend_schema(request=None, responses={202: KnowledgeDocumentSerializer})
    @action(detail=True, methods=["post"])
    def reindex(self, request, pk=None):
        document = self.get_object()
        document.status = KnowledgeDocument.Status.PROCESSING
        document.error = ""
        document.save(update_fields=["status", "error"])
        _queue(tasks.index_document, document.pk)
        return Response(self.get_serializer(document).data, status=status.HTTP_202_ACCEPTED)


def _counts(model, missing=0, pending=("pending",)):
    rows = {row["status"]: row["n"]
            for row in model.objects.order_by().values("status").annotate(n=Count("pk"))}
    return {
        "ready": rows.get("ready", 0),
        "pending": sum(rows.get(value, 0) for value in pending) + missing,
        "failed": rows.get("failed", 0),
    }


class IndexStatusView(APIView):
    """How much of the catalog and knowledge base is searchable, and what failed."""

    permission_classes = [IsShopAdmin]
    FAILURE_LIMIT = 50

    @extend_schema(responses=IndexStatusSerializer)
    def get(self, request):
        failures = [
            {"kind": "product", "id": entry.product_id, "name": entry.product.name, "error": entry.error}
            for entry in ProductIndex.objects.filter(status=IndexStatus.FAILED)
            .select_related("product")[: self.FAILURE_LIMIT]
        ]
        failures += [
            {"kind": "image", "id": entry.image_id, "name": f"{entry.product.name} (photo {entry.image_id})",
             "error": entry.error}
            for entry in ProductImageIndex.objects.filter(status=IndexStatus.FAILED)
            .select_related("product")[: self.FAILURE_LIMIT]
        ]
        failures += [
            {"kind": "knowledge", "id": document.pk, "name": document.title, "error": document.error}
            for document in KnowledgeDocument.objects.filter(status=KnowledgeDocument.Status.FAILED)
            [: self.FAILURE_LIMIT]
        ]
        return Response({
            "products": _counts(ProductIndex, missing=Product.objects.filter(ai_index__isnull=True).count()),
            "images": _counts(ProductImageIndex, missing=ProductImage.objects.filter(ai_index__isnull=True).count()),
            "knowledge": _counts(KnowledgeDocument, pending=("processing",)),
            "failures": failures,
        })


class ReindexView(APIView):
    """Queue a rebuild of the product and/or knowledge indexes."""

    permission_classes = [IsShopAdmin]

    @extend_schema(request=ReindexRequestSerializer, responses={202: ReindexRequestSerializer})
    def post(self, request):
        data = ReindexRequestSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        _queue(tasks.reindex_all, **data.validated_data)
        return Response(data.validated_data, status=status.HTTP_202_ACCEPTED)


@extend_schema(parameters=[OpenApiParameter("state", str, enum=Conversation.State.values,
                                            description="Only conversations in this state.")])
class AdminConversationViewSet(viewsets.ReadOnlyModelViewSet):
    """Assistant conversations, e.g. the ones handed to staff (state=needs_human)."""

    permission_classes = [IsShopAdmin]

    def get_queryset(self):
        last_text = (ChatMessage.objects.filter(conversation=OuterRef("pk"))
                     .order_by("-created_at", "-id").values("text")[:1])
        qs = (Conversation.objects.select_related("user").annotate(last_message=Subquery(last_text))
              .order_by("-updated_at"))
        state = self.request.query_params.get("state")
        if state:
            qs = qs.filter(state=state)
        if self.action == "retrieve":
            qs = qs.prefetch_related("messages")
        return qs

    def get_serializer_class(self):
        return AdminConversationDetailSerializer if self.action == "retrieve" else AdminConversationSerializer

    @extend_schema(request=None, responses=AdminConversationSerializer)
    @action(detail=True, methods=["post"])
    def release(self, request, pk=None):
        conversation = self.get_object()
        conversation.state = Conversation.State.ACTIVE
        conversation.handoff_reason = ""
        conversation.save(update_fields=["state", "handoff_reason", "updated_at"])
        return Response(AdminConversationSerializer(self.get_queryset().get(pk=conversation.pk)).data)
