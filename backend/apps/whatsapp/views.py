import json
import logging

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import OuterRef, Subquery
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.accounts.permissions import IsShopAdmin
from apps.ai.models import ChatMessage, Conversation
from apps.orders.services import normalize_phone

from . import linking, outbound, parsing, staff, texts
from .models import (
    WhatsAppContact,
    WhatsAppInboundMessage as Inbound,
    WhatsAppOrderNotification,
    WhatsAppOutboundMessage as Out,
)
from .serializers import (
    STAFF_TEMPLATES,
    CodeSerializer,
    DetailSerializer,
    LinkCodeSerializer,
    LinkStatusSerializer,
    OutboundSerializer,
    StaffReplyResultSerializer,
    StaffReplySerializer,
    WindowClosedSerializer,
)
from .signature import verify_signature, verify_token

logger = logging.getLogger(__name__)

STATUS_RANK = {Out.Status.QUEUED: 0, Out.Status.SENT: 1, Out.Status.DELIVERED: 2, Out.Status.READ: 3}
FINAL = {Out.Status.FAILED, Out.Status.SKIPPED}


def contact_phone(wa_id):
    try:
        return normalize_phone(wa_id)
    except DjangoValidationError:
        return ("+" + "".join(ch for ch in wa_id if ch.isdigit()))[:16]


def upsert_contact(wa_id, name):
    contact, created = WhatsAppContact.objects.get_or_create(
        wa_id=wa_id, defaults={"phone": contact_phone(wa_id), "profile_name": name[:120]},
    )
    if not created and name and contact.profile_name != name[:120]:
        contact.profile_name = name[:120]
        contact.save(update_fields=["profile_name", "updated_at"])
    return contact


def apply_status(status):
    row = Out.objects.select_for_update().filter(wa_message_id=status.id).first()
    if row is None:
        logger.info("WhatsApp status %s for unknown message %s ignored.", status.status, status.id)
        return
    if row.status in FINAL:
        return
    if status.status == Out.Status.FAILED:
        row.status, row.error_code, row.error = Out.Status.FAILED, status.error_code, status.error_title
    elif status.status in STATUS_RANK and STATUS_RANK[status.status] > STATUS_RANK.get(row.status, 0):
        row.status = status.status
    else:
        return
    row.status_at = status.at
    row.save(update_fields=["status", "status_at", "error_code", "error"])


def ingest(changes):
    """Store new messages once (unique wamid) and apply status callbacks. Returns the contacts with
    new messages, whose drain is queued after commit."""
    from .tasks import drain_contact

    to_drain = set()
    with transaction.atomic():
        for change in changes:
            if change.phone_number_id != settings.WHATSAPP_PHONE_NUMBER_ID:
                logger.info("WhatsApp notification for number %s ignored.", change.phone_number_id)
                continue
            for message in change.messages:
                contact = upsert_contact(message.wa_id, change.contacts.get(message.wa_id, ""))
                _, created = Inbound.objects.get_or_create(
                    wa_message_id=message.id,
                    defaults={"contact": contact, "type": message.type, "raw_type": message.raw_type,
                              "sent_at": message.sent_at, "text": message.text,
                              "button_id": message.button_id, "media_id": message.media_id,
                              "media_mime": message.media_mime[:64]},
                )
                if created:
                    to_drain.add(contact.pk)
            for status in change.statuses:
                apply_status(status)
        for contact_id in sorted(to_drain):
            transaction.on_commit(lambda pk=contact_id: drain_contact.delay(pk))
    return to_drain


class WebhookView(APIView):
    """Meta WhatsApp Cloud API webhook: subscription handshake and signed notifications."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = []

    @extend_schema(
        tags=["whatsapp-webhook"],
        parameters=[OpenApiParameter("hub.mode", str), OpenApiParameter("hub.verify_token", str),
                    OpenApiParameter("hub.challenge", str)],
        responses={(200, "text/plain"): OpenApiTypes.STR, 403: None},
    )
    def get(self, request):
        params = request.query_params
        if params.get("hub.mode") == "subscribe" and verify_token(params.get("hub.verify_token")):
            return HttpResponse(params.get("hub.challenge", ""), content_type="text/plain")
        return HttpResponse(status=403)

    @extend_schema(tags=["whatsapp-webhook"], request=OpenApiTypes.OBJECT,
                   responses={200: OpenApiTypes.OBJECT, 403: None})
    def post(self, request):
        raw = request.body  # the signature covers these exact bytes (R1)
        if not verify_signature(raw, request.headers.get("X-Hub-Signature-256")):
            return HttpResponse(status=403)
        try:
            payload = json.loads(raw)
        except ValueError:
            logger.warning("WhatsApp webhook body is not JSON; ignored.")
            return JsonResponse({"ok": True})
        ingest(parsing.parse(payload))
        return JsonResponse({"ok": True})


# --- Account linking (contracts/link-api.md) ------------------------------------------------------


class LinkView(APIView):
    """The signed-in user's WhatsApp link: show it, or unlink the number."""

    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["whatsapp"], responses={200: LinkStatusSerializer})
    def get(self, request):
        contact = WhatsAppContact.objects.filter(user=request.user).first()
        return Response(LinkStatusSerializer({
            "linked": contact is not None,
            "number": linking.mask(contact.phone) if contact else None,
            "linked_at": contact.linked_at if contact else None,
            "business_number": settings.WHATSAPP_BUSINESS_NUMBER,
        }).data)

    @extend_schema(tags=["whatsapp"], request=None, responses={204: None})
    def delete(self, request):
        linking.unlink(request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class LinkCodeView(APIView):
    """Issue a one-time code the shopper sends from WhatsApp to link that number."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "whatsapp_link_code"

    @extend_schema(tags=["whatsapp"], request=None,
                   responses={201: LinkCodeSerializer, 429: DetailSerializer, 503: DetailSerializer})
    def post(self, request):
        try:
            body = linking.issue_code(request.user)
        except linking.NotConfigured:
            return Response({"detail": "WhatsApp is not configured."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response(LinkCodeSerializer(body).data, status=status.HTTP_201_CREATED)


# --- Staff tools (contracts/admin-api.md, US4) ----------------------------------------------------

WINDOW_CLOSED_DETAIL = ("The shopper's last message was more than 24 hours ago. "
                        "Only the approved follow-up template can be sent.")


class StaffReplyView(APIView):
    """Send a staff message to the shopper of a WhatsApp conversation. Free text needs the 24-hour
    window; the follow-up template can be sent at any time. The conversation state is unchanged."""

    permission_classes = [IsShopAdmin]

    @extend_schema(tags=["whatsapp"], request=StaffReplySerializer,
                   responses={202: StaffReplyResultSerializer, 400: CodeSerializer, 409: WindowClosedSerializer})
    def post(self, request, pk):
        conversation = get_object_or_404(Conversation, pk=pk)
        data = StaffReplySerializer(data=request.data)
        data.is_valid(raise_exception=True)
        contact = staff.contact_for(conversation)
        if contact is None:
            return Response({"code": "not_whatsapp", "detail": "This is not a WhatsApp conversation."},
                            status=status.HTTP_400_BAD_REQUEST)

        Trigger = Out.Trigger
        try:
            with transaction.atomic():
                if data.validated_data.get("template"):
                    text = texts.text("follow_up", contact.language)
                    rows = [outbound.queue_template(
                        contact, settings.WHATSAPP_TEMPLATE_FOLLOW_UP, [], Trigger.STAFF, conversation,
                        staff_user=request.user, text=text)]
                else:
                    text = data.validated_data["text"]
                    rows = outbound.queue_text(contact, text, Trigger.STAFF, conversation, staff_user=request.user)
                ChatMessage.objects.create(conversation=conversation, role=ChatMessage.Role.STAFF, text=text,
                                           language=conversation.language,
                                           payload={"whatsapp": {"staff_user": request.user.username}})
                Conversation.objects.filter(pk=conversation.pk).update(updated_at=timezone.now())
                outbound.flush(rows[0].batch)
        except outbound.WindowClosed:
            return Response({"code": "window_closed", "detail": WINDOW_CLOSED_DETAIL, "templates": STAFF_TEMPLATES},
                            status=status.HTTP_409_CONFLICT)
        return Response({"outbound_id": rows[0].pk, "status": rows[0].status}, status=status.HTTP_202_ACCEPTED)


@extend_schema(tags=["whatsapp"], parameters=[
    OpenApiParameter("status", str, enum=Out.Status.values, description="Only messages in this state."),
    OpenApiParameter("contact", int, description="Only messages to this contact id."),
])
class OutboundListView(ListAPIView):
    """Messages sent (or not) to shoppers; ?status=failed finds failed sends and order updates."""

    permission_classes = [IsShopAdmin]
    serializer_class = OutboundSerializer

    def get_queryset(self):
        order_number = (WhatsAppOrderNotification.objects.filter(outbound=OuterRef("pk"))
                        .values("order__number")[:1])
        qs = (Out.objects.select_related("contact").annotate(order_number=Subquery(order_number))
              .order_by("-created_at", "-id"))
        params = self.request.query_params
        if params.get("status"):
            qs = qs.filter(status=params["status"])
        if params.get("contact"):
            contact = params["contact"]
            qs = qs.filter(contact_id=int(contact)) if contact.isdigit() else qs.none()
        return qs
