"""Who counts as a rider, and how loaded they are (data-model.md "Active rider", research R6/R8)."""

from django.db.models import Count, Q

from apps.accounts.models import User

from .models import ACTIVE


def active_riders():
    return User.objects.filter(role=User.Role.RIDER, is_active=True, rider_profile__isnull=False)


def assignable_riders():
    return active_riders().filter(rider_profile__is_available=True)


def annotate_open_jobs(queryset):
    return queryset.annotate(
        open_jobs=Count("deliveries", filter=Q(deliveries__status__in=ACTIVE), distinct=True)
    )


def open_jobs(rider):
    return rider.deliveries.filter(status__in=ACTIVE).count()


def rider_for_contact(contact):
    """The active rider whose phone is this WhatsApp contact's number, else None (R6)."""
    if not contact.phone:
        return None
    return active_riders().select_related("rider_profile").filter(phone=contact.phone).first()


def resolve_rider(job):
    """whatsapp.processing.ROLE_RESOLVERS hook."""
    return rider_for_contact(job.contact)


def rider_stop_control(job):
    """CONTROL_HANDLERS hook, ahead of updates_control: an active rider can't switch job messages
    off with STOP; they are told to ask the admin instead (edge case "rider sends STOP")."""
    from apps.whatsapp import processing
    from apps.whatsapp.models import WhatsAppInboundMessage as Inbound

    from . import texts

    if job.rider is None or job.inbound.type != Inbound.Type.TEXT:
        return None
    if (job.inbound.text or "").strip().lower() not in processing.STOP_WORDS:
        return None
    processing.record(job)
    processing.send_system(job, texts.text("rider_stop", job.lang))
    return Inbound.Status.ANSWERED, ""
