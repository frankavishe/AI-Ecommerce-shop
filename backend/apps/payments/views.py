import hmac
import logging

from django.conf import settings
from django.db import transaction
from django.http import Http404
from drf_spectacular.utils import extend_schema
from rest_framework.parsers import JSONParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Payment
from .services import apply_provider_status
from .stakaba import normalise_transaction
from .tasks import confirm_payment

logger = logging.getLogger(__name__)


def _find_payment(tx, body):
    """internalReference -> provider_ref, falling back to metadata.orderId -> our reference
    (covers a create call that timed out before we saw its internalReference)."""
    ref = tx["internal_reference"]
    payments = Payment.objects.select_for_update()
    if ref:
        payment = payments.filter(provider_ref=ref).first()
        if payment:
            return payment
    metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else {}
    order_ref = metadata.get("orderId")
    if not order_ref:
        return None
    payment = payments.filter(reference=str(order_ref)).first()
    if payment and payment.provider_ref and ref and payment.provider_ref != ref:
        logger.warning("Stakaba webhook %s claims payment %s, which is %s", ref, order_ref, payment.provider_ref)
        return None
    return payment


class StakabaWebhookView(APIView):
    """transaction.success / transaction.failed events.

    Stakaba doesn't sign webhooks and the status lookup needs a dashboard login, so the secret
    token in the URL is what authenticates the call (see stakaba.md "Webhook trust"). With
    STAKABA_CONFIRM_VIA_API on, the body is only a trigger and the API decides.
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    parser_classes = [JSONParser]

    @extend_schema(request=dict, responses={200: dict})
    def post(self, request, token):
        expected = settings.STAKABA_WEBHOOK_TOKEN
        if not expected or not hmac.compare_digest(str(token), expected):
            raise Http404

        body = request.data if isinstance(request.data, dict) else {}
        tx = normalise_transaction(body)
        confirm_later = None
        with transaction.atomic():
            payment = _find_payment(tx, body)
            if payment is None:
                logger.info("Stakaba webhook for unknown reference %r ignored", tx["internal_reference"])
                return Response({"received": True})
            payment.raw_payload = {**payment.raw_payload, "webhook": body}
            fields = ["raw_payload", "updated_at"]
            if not payment.provider_ref and tx["internal_reference"]:
                payment.provider_ref = tx["internal_reference"][:100]
                fields.append("provider_ref")
            payment.save(update_fields=fields)

            if payment.status != Payment.Status.SUCCESS:
                if settings.STAKABA_CONFIRM_VIA_API:
                    confirm_later = payment.id
                else:
                    apply_provider_status(payment, tx)
        if confirm_later:
            confirm_payment.delay(confirm_later)
        # Always 200 once recorded, even for failures, so Stakaba stops retrying.
        return Response({"received": True})
