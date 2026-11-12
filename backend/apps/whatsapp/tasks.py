"""Celery tasks for the WhatsApp channel."""

from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from . import outbound
from .locks import advisory_lock
from .models import WhatsAppInboundMessage as Inbound

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
