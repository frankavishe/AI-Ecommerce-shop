"""Order updates on WhatsApp (research R14, US5).

orders.services.transition() writes an OrderEvent for every status change, so one receiver on it
sees each change once. The task does the rest after the commit (and is idempotent by itself).
"""

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.orders.models import Order, OrderEvent

S = Order.Status
NOTIFIED_STATUSES = {S.PAID, S.OUT_FOR_DELIVERY, S.DELIVERED, S.CANCELLED, S.EXPIRED}


@receiver(post_save, sender=OrderEvent, dispatch_uid="whatsapp.order_event")
def order_event_saved(sender, instance, created, raw=False, **kwargs):
    if not created or raw or instance.status not in NOTIFIED_STATUSES:
        return
    from .tasks import notify_order_status

    order_id, status = instance.order_id, instance.status
    transaction.on_commit(lambda: notify_order_status.delay(order_id, status))
