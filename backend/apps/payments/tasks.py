from celery import shared_task
from django.db import transaction

from . import stakaba
from .models import Payment
from .services import apply_provider_status
from .stakaba import PaymentProviderUnavailable


@shared_task(bind=True, max_retries=5)
def confirm_payment(self, payment_id):
    """Ask Stakaba for the transaction's real status and apply it. Safe to run any number of times.

    Only used when STAKABA_CONFIRM_VIA_API is on (GET /transactions/{ref} is Bearer-only today).
    """
    payment = Payment.objects.filter(pk=payment_id).first()
    if payment is None or payment.status == Payment.Status.SUCCESS or not payment.provider_ref:
        return
    try:
        tx = stakaba.get_client().get_transaction(payment.provider_ref)
    except PaymentProviderUnavailable as exc:
        # Exponential backoff (30s, 60s, 120s, ...) as Stakaba asks for 429/5xx.
        raise self.retry(exc=exc, countdown=30 * 2 ** self.request.retries)
    if tx is None:  # Stakaba doesn't have it (yet): still pending
        return
    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(pk=payment_id)
        payment.raw_payload = {**payment.raw_payload, "query": {**tx, "amount": None if tx["amount"] is None else str(tx["amount"])}}
        payment.save(update_fields=["raw_payload", "updated_at"])
        apply_provider_status(payment, tx)
