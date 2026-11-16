"""Celery tasks for the WhatsApp channel."""

from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import outbound
from .locks import advisory_lock
from .models import (
    WhatsAppInboundMessage as Inbound,
    WhatsAppOrder,
    WhatsAppOrderNotification as Note,
    WhatsAppOutboundMessage as Out,
)
from .texts import format_tzs

RETRY_COUNTDOWNS = [10, 60, 300]  # 4 attempts in all (R10)


@shared_task(bind=True, max_retries=len(RETRY_COUNTDOWNS))
def deliver(self, batch_id):
    """Send one batch in order. Eager runs (tests, local) never retry."""
    retries = self.request.retries or 0
    last = bool(self.request.is_eager) or retries >= len(RETRY_COUNTDOWNS)
    if outbound.deliver_batch(batch_id, last_attempt=last) == "retry":
        raise self.retry(countdown=RETRY_COUNTDOWNS[retries])
    return "done"


def _next_received(contact_id):
    return (Inbound.objects.filter(contact_id=contact_id, status=Inbound.Status.RECEIVED)
            .select_related("contact").order_by("sent_at", "id").first())


@shared_task(soft_time_limit=settings.AI_CHAT_TIMEOUT + 60)
def drain_contact(contact_id):
    """Process one number's messages one at a time, in send order (research R3)."""
    from . import processing

    while True:
        with advisory_lock(contact_id) as got:
            if not got:
                return "busy"  # the holder picks up our row before it lets go
            stale = timezone.now() - timedelta(seconds=settings.AI_CHAT_TIMEOUT + 120)
            Inbound.objects.filter(contact_id=contact_id, status=Inbound.Status.PROCESSING,
                                   received_at__lt=stale).update(status=Inbound.Status.RECEIVED)
            while (inbound := _next_received(contact_id)) is not None:
                processing.process(inbound)
        # a message stored between our last check and the unlock found the lock held: look again
        if not Inbound.objects.filter(contact_id=contact_id, status=Inbound.Status.RECEIVED).exists():
            return "done"


def _template_for(status):
    return {
        "paid": settings.WHATSAPP_TEMPLATE_ORDER_PAID,
        "out_for_delivery": settings.WHATSAPP_TEMPLATE_ORDER_OUT_FOR_DELIVERY,
        "delivered": settings.WHATSAPP_TEMPLATE_ORDER_DELIVERED,
        "cancelled": settings.WHATSAPP_TEMPLATE_ORDER_CANCELLED,
        "expired": settings.WHATSAPP_TEMPLATE_ORDER_EXPIRED,
    }.get(status)


@shared_task
def notify_order_status(order_id, status):
    """One template per status change of an order placed on WhatsApp (research R14). A replay finds
    the notification row and stops; the send result reaches the row through deliver_batch."""
    template = _template_for(status)
    link = WhatsAppOrder.objects.select_related("order", "contact").filter(order_id=order_id).first()
    if template is None or link is None:
        return "not_whatsapp"
    order, contact = link.order, link.contact
    with transaction.atomic():
        note, created = Note.objects.get_or_create(order=order, status=status)
        if not created:
            return "duplicate"
        if not contact.updates_allowed:
            note.state = Note.State.SKIPPED
            note.save(update_fields=["state"])
            return "skipped"
        values = [order.number, format_tzs(order.total)] if status == "paid" else [order.number]
        row = outbound.queue_template(contact, template, values, Out.Trigger.ORDER_UPDATE)
        note.outbound = row
        note.save(update_fields=["outbound"])
        outbound.flush(row.batch)
    return "queued"
