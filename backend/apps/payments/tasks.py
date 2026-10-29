from celery import shared_task
from django.db import transaction

from . import clickpesa
from .clickpesa import PaymentProviderUnavailable
from .models import Payment
from .services import apply_provider_status


@shared_task(bind=True, max_retries=5, default_retry_delay=60)
def confirm_payment(self, payment_id):
    """Ask ClickPesa for the payment's real status and apply it. Safe to run any number of times."""
    payment = Payment.objects.filter(pk=payment_id).first()
    if payment is None or payment.status == Payment.Status.SUCCESS:
        return
    try:
        records = clickpesa.get_client().query_payments(payment.reference)
    except PaymentProviderUnavailable as exc:
        raise self.retry(exc=exc)
    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(pk=payment_id)
        apply_provider_status(payment, records)
