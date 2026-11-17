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
