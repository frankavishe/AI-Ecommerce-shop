"""OrderEvent receiver (research R3): a paid order gets its delivery; a cancelled order closes it.

It reacts only to `paid` and `cancelled`, which delivery itself never produces, so the statuses
change() drives (processing, out_for_delivery, delivered) never loop back here (R4).
"""

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.orders.models import Order, OrderEvent

S = Order.Status


def paid(order_id):
    from . import services

    order = Order.objects.get(pk=order_id)
    delivery, created = services.create_for_order(order)
    if created:
        services.auto_assign(delivery)


@receiver(post_save, sender=OrderEvent, dispatch_uid="delivery.order_event")
def order_event_saved(sender, instance, created, raw=False, **kwargs):
    if not created or raw:
        return
    if instance.status == S.PAID:
        order_id = instance.order_id
        transaction.on_commit(lambda: paid(order_id))
    elif instance.status == S.CANCELLED:
        from . import services

        services.cancel_for_order(instance.order)
