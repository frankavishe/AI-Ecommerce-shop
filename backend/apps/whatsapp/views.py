import json
import logging

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from apps.orders.services import normalize_phone

from . import parsing
from .models import WhatsAppContact, WhatsAppInboundMessage as Inbound, WhatsAppOutboundMessage as Out
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
