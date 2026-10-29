"""Payment rules. ClickPesa's status query is the source of truth, never a webhook body (R3)."""

import logging
from decimal import Decimal, InvalidOperation

from django.db import transaction

from apps.orders import services as orders
from apps.orders.models import Order, OrderEvent

from . import clickpesa
from .clickpesa import PaymentProviderUnavailable
from .models import Payment

logger = logging.getLogger(__name__)

PAID_STATUSES = {"SUCCESS", "SETTLED"}
PROVIDER = OrderEvent.Source.PROVIDER


def start_payment(order):
    """Create a payment attempt with its own reference and a ClickPesa checkout link.

    Returns (payment, None) on success or (None, error message) when ClickPesa is unavailable.
    """
    with transaction.atomic():
        locked = Order.objects.select_for_update().get(pk=order.pk)
        reference = f"{locked.number}P{locked.payments.count() + 1}"
        payment = Payment.objects.create(order=locked, reference=reference, amount=locked.total)
    try:
        link = clickpesa.get_client().create_checkout_link(
            reference, order.total, order.contact_name, order.contact_phone,
            f"Order {order.number}",
        )
    except PaymentProviderUnavailable as exc:
        # Keep the attempt (the reference may already exist at ClickPesa) but mark it unusable.
        payment.status = Payment.Status.FAILED
        payment.raw_payload = {"error": str(exc)}
        payment.save(update_fields=["status", "raw_payload", "updated_at"])
        return None, "The payment service is unavailable right now. Please try again shortly."
    payment.checkout_link = link
    payment.save(update_fields=["checkout_link", "updated_at"])
    return payment, None


def _amount(record):
    try:
        return Decimal(str(record.get("collectedAmount")))
    except (InvalidOperation, TypeError):
        return Decimal("0")


def _flag_for_review(order, note):
    if Order.Status.NEEDS_REVIEW in orders.TRANSITIONS.get(order.status, set()):
        orders.transition(order, Order.Status.NEEDS_REVIEW, PROVIDER, note=note)
    elif order.status != Order.Status.NEEDS_REVIEW:
        # Final states (e.g. cancelled) keep their status; the timeline still shows the money.
        OrderEvent.objects.create(order=order, status=order.status, source=PROVIDER, note=note)


def apply_provider_status(payment, records):
    """Apply ClickPesa query records to a payment (call with the payment row locked)."""
    payment.raw_payload = {**payment.raw_payload, "query": records}
    fields = ["raw_payload", "updated_at"]
    if payment.status == Payment.Status.SUCCESS:
        payment.save(update_fields=fields)
        return payment

    order = Order.objects.select_for_update().get(pk=payment.order_id)
    paid = [r for r in records if r.get("status") in PAID_STATUSES and r.get("collectedCurrency", "TZS") == "TZS"]
    if paid:
        record = max(paid, key=_amount)
        payment.collected_amount = _amount(record)
        payment.provider_ref = str(record.get("paymentReference") or record.get("id") or "")[:100]
        payment.channel = str(record.get("channel") or "")[:60]
        fields += ["collected_amount", "provider_ref", "channel", "status"]
        if payment.collected_amount >= order.total:
            payment.status = Payment.Status.SUCCESS
            payment.save(update_fields=fields)
            if order.status == Order.Status.AWAITING_PAYMENT:
                orders.transition(order, Order.Status.PAID, PROVIDER, note=f"Payment {payment.reference}")
            else:
                _flag_for_review(order, f"Payment {payment.reference} received while order was {order.status}.")
        else:
            payment.status = Payment.Status.MISMATCH
            payment.save(update_fields=fields)
            _flag_for_review(
                order,
                f"Payment {payment.reference} collected {payment.collected_amount} of {order.total} TZS.",
            )
        return payment

    statuses = {r.get("status") for r in records}
    if "FAILED" in statuses and not statuses & {"PENDING", "PROCESSING"}:
        payment.status = Payment.Status.FAILED
        fields.append("status")
    payment.save(update_fields=fields)
    return payment
