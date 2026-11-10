from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import NotFound
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.orders.models import Cart
from apps.orders.services import GUEST_CART_LIFETIME, merge_carts

from . import agent
from .models import Conversation
from .serializers import ChatRequestSerializer, ChatResponseSerializer
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
