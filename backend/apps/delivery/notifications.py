"""WhatsApp messages and inbox entries for delivery changes (research R7, contracts/notifications.md).

`deliver_notices` is registered in services.NOTIFY_HOOKS: it runs inside change()'s transaction, so
the DeliveryNotification and inbox rows commit together with the event; the send itself goes out
on commit through whatsapp.outbound, and a failed send never rolls the delivery change back.
"""

from django.conf import settings

from apps.whatsapp import outbound
from apps.whatsapp.models import WhatsAppContact
from apps.whatsapp.models import WhatsAppOutboundMessage as Out

from . import texts
from .models import DeliveryNotification as Note
from .models import RiderInboxEntry

RIDER_KINDS = {
    "assigned": (Note.Kind.RIDER_ASSIGNED, "WHATSAPP_TEMPLATE_DELIVERY_ASSIGNED"),
    "removed": (Note.Kind.RIDER_REMOVED, "WHATSAPP_TEMPLATE_DELIVERY_REMOVED"),
    "cancelled": (Note.Kind.RIDER_CANCELLED, "WHATSAPP_TEMPLATE_DELIVERY_CANCELLED"),
}
# Extra senders for other notice kinds (US3 registers "customer_failed").
NOTICE_SENDERS = {}


def rider_contact(user):
    """The WhatsApp contact for a rider's phone (created on first message, R7)."""
    contact, _ = WhatsAppContact.objects.get_or_create(
        phone=user.phone, defaults={"wa_id": user.phone.lstrip("+"), "language": user.preferred_language},
    )
    return contact


def _next_attempt(**lookup):
    last = Note.objects.filter(**lookup).order_by("-attempt").values_list("attempt", flat=True).first()
    return (last or 0) + 1


def send_template(contact, name, params, language):
    """Queue one approved template in `language` and deliver it after the commit."""
    row = outbound.queue_template(contact, name, params, Out.Trigger.ORDER_UPDATE, language=language)
    outbound.flush(row.batch)
    return row


def job_params(delivery):
    order = delivery.order
    return [order.number, order.region, order.street, order.contact_name,
            sum(item.quantity for item in order.items.all())]


def notify_rider(delivery, rider, kind):
    note_kind, setting = RIDER_KINDS[kind]
    number = delivery.order.number
    # rider notices may repeat for one delivery (assigned, removed, assigned again): `attempt`
    # counts them; replays can't happen because change() turns a repeated status into a no-op.
    note = Note.objects.create(delivery=delivery, rider=rider, kind=note_kind,
                               attempt=_next_attempt(delivery=delivery, rider=rider, kind=note_kind))
    RiderInboxEntry.objects.create(
        rider=rider, kind=kind, delivery=delivery,
        title_sw=texts.text(f"inbox_{kind}", "sw", number=number),
        title_en=texts.text(f"inbox_{kind}", "en", number=number),
    )
    if not rider.phone:
        note.state = Note.State.SKIPPED
        note.save(update_fields=["state"])
        return note
    params = job_params(delivery) if kind == "assigned" else [number]
    note.outbound = send_template(rider_contact(rider), getattr(settings, setting), params,
                                  rider.preferred_language)
    note.save(update_fields=["outbound"])
    return note


def deliver_notices(delivery, notices):
    for kind, rider in notices:
        if kind in RIDER_KINDS:
            notify_rider(delivery, rider, kind)
        elif kind in NOTICE_SENDERS:
            NOTICE_SENDERS[kind](delivery)
