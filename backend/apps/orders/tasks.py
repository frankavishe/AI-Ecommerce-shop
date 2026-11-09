"""Scheduled jobs (Celery beat, every 5 minutes; see CELERY_BEAT_SCHEDULE)."""

from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import services
from .models import Order, OrderEvent

BATCH = 500


def _each_locked(**conditions):
    """Yield matching orders one at a time, each locked in its own transaction.

    Rows another worker holds are skipped; the next run picks them up.
    """
    ids = list(Order.objects.filter(**conditions).values_list("pk", flat=True)[:BATCH])
    for pk in ids:
        with transaction.atomic():
            order = Order.objects.select_for_update(skip_locked=True).filter(pk=pk, **conditions).first()
            if order is not None:
                yield order


@shared_task
def send_payment_reminders():
    """Record one reminder for orders still unpaid after ORDER_REMINDER_MINUTES.

    Delivering it (WhatsApp/SMS) belongs to a later feature; this marks it as due and sent.
    """
    cutoff = timezone.now() - timedelta(minutes=settings.ORDER_REMINDER_MINUTES)
    sent = 0
    for order in _each_locked(
        status=Order.Status.AWAITING_PAYMENT, reminder_sent_at=None, placed_at__lte=cutoff
    ):
        order.reminder_sent_at = timezone.now()
        order.save(update_fields=["reminder_sent_at"])
        OrderEvent.objects.create(
            order=order, status=order.status, source=OrderEvent.Source.SYSTEM,
            note="Payment reminder sent",
        )
        sent += 1
    return sent


@shared_task
def expire_unpaid_orders():
    """Expire orders unpaid past expires_at and return their stock."""
    expired = 0
    for order in _each_locked(status=Order.Status.AWAITING_PAYMENT, expires_at__lte=timezone.now()):
        services.transition(
            order, Order.Status.EXPIRED, OrderEvent.Source.SYSTEM, note="Not paid in time"
        )
        expired += 1
    return expired
