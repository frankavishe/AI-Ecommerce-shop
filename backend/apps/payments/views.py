import logging

from django.conf import settings
from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework.parsers import JSONParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .clickpesa import verify_checksum
from .models import Payment
from .tasks import confirm_payment

logger = logging.getLogger(__name__)


def _checksum_ok(payload, data, key):
    """ClickPesa's docs don't pin where the checksum sits in webhooks, so accept both (R4)."""
    if "checksum" in payload:
        return verify_checksum(payload, payload["checksum"], key)
    if "checksum" in data:
        return verify_checksum(data, data["checksum"], key)
    return False


class ClickPesaWebhookView(APIView):
    """PAYMENT RECEIVED / PAYMENT FAILED events. The body only triggers a status query."""

    authentication_classes = []
    permission_classes = [AllowAny]
    parser_classes = [JSONParser]

    @extend_schema(request=dict, responses={200: dict, 400: dict})
    def post(self, request):
        payload = request.data if isinstance(request.data, dict) else {}
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}

        key = settings.CLICKPESA_CHECKSUM_KEY
        if key and not _checksum_ok(payload, data, key):
            logger.warning("ClickPesa webhook rejected: invalid checksum")
            return Response({"detail": "Invalid checksum.", "code": "invalid_checksum"}, status=400)

        reference = data.get("orderReference") or payload.get("orderReference")
        with transaction.atomic():
            payment = Payment.objects.select_for_update().filter(reference=reference).first()
            if payment is None:
                logger.info("ClickPesa webhook for unknown reference %r ignored", reference)
                return Response({"received": True})
            payment.raw_payload = {**payment.raw_payload, "webhook": payload}
            payment.save(update_fields=["raw_payload", "updated_at"])
        confirm_payment.delay(payment.id)
        return Response({"received": True})
