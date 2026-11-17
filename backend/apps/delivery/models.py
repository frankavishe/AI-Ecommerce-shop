"""Delivery jobs, their timeline, rider notifications and the rider inbox (specs/005, data-model.md)."""

from django.conf import settings
from django.db import models
from django.db.models import Q


class Delivery(models.Model):
    class Status(models.TextChoices):
        WAITING = "waiting", "Waiting for a rider"
        ASSIGNED = "assigned", "Assigned"
        PICKED_UP = "picked_up", "Picked up"
        ON_THE_WAY = "on_the_way", "On the way"
        DELIVERED = "delivered", "Delivered"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    order = models.OneToOneField("orders.Order", on_delete=models.PROTECT, related_name="delivery")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.WAITING)
    rider = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="deliveries"
    )
    attempt = models.PositiveSmallIntegerField(default=1)
    failure_reason = models.CharField(max_length=255, blank=True)
    assigned_at = models.DateTimeField(null=True, blank=True)
    picked_up_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "deliveries"
        indexes = [
            models.Index(fields=["status", "created_at"], name="delivery_status_created"),
            models.Index(fields=["rider", "status"], name="delivery_rider_status"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=~Q(status__in=["assigned", "picked_up", "on_the_way"]) | Q(rider__isnull=False),
                name="delivery_active_has_rider",
            )
        ]

    def __str__(self):
        return f"Delivery {self.order_id} ({self.status})"


S = Delivery.Status
OPEN = frozenset({S.WAITING, S.ASSIGNED, S.PICKED_UP, S.ON_THE_WAY})
ACTIVE = frozenset({S.ASSIGNED, S.PICKED_UP, S.ON_THE_WAY})


class DeliveryEvent(models.Model):
    class Actor(models.TextChoices):
        ADMIN = "admin", "Admin"
        RIDER = "rider", "Rider"
        SYSTEM = "system", "System"

    delivery = models.ForeignKey(Delivery, on_delete=models.CASCADE, related_name="events")
    status = models.CharField(max_length=12, choices=Delivery.Status.choices)
    attempt = models.PositiveSmallIntegerField()
    rider = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    actor_type = models.CharField(max_length=8, choices=Actor.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


class DeliveryNotification(models.Model):
    class Kind(models.TextChoices):
        RIDER_WELCOME = "rider_welcome", "Rider welcome"
        RIDER_ASSIGNED = "rider_assigned", "Job assigned"
        RIDER_REMOVED = "rider_removed", "Job removed"
        RIDER_CANCELLED = "rider_cancelled", "Job cancelled"
        CUSTOMER_FAILED = "customer_failed", "Customer: couldn't deliver"

    class State(models.TextChoices):
        QUEUED = "queued", "Queued"
        SKIPPED = "skipped", "Skipped"
        FAILED = "failed", "Failed"

    delivery = models.ForeignKey(
        Delivery, null=True, blank=True, on_delete=models.CASCADE, related_name="notifications"
    )
    rider = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    attempt = models.PositiveSmallIntegerField(default=1)
    outbound = models.ForeignKey(
        "whatsapp.WhatsAppOutboundMessage", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    state = models.CharField(max_length=8, choices=State.choices, default=State.QUEUED)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["delivery", "rider", "kind", "attempt"], name="delivery_notification_once",
                nulls_distinct=False,
            ),
            models.UniqueConstraint(
                fields=["rider", "kind", "attempt"], condition=Q(delivery__isnull=True),
                name="delivery_notification_rider_once",
            ),
        ]


class RiderInboxEntry(models.Model):
    class Kind(models.TextChoices):
        ASSIGNED = "assigned", "Assigned"
        REMOVED = "removed", "Removed"
        CANCELLED = "cancelled", "Cancelled"

    rider = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="inbox")
    kind = models.CharField(max_length=12, choices=Kind.choices)
    delivery = models.ForeignKey(Delivery, on_delete=models.CASCADE, related_name="+")
    title_sw = models.CharField(max_length=160)
    title_en = models.CharField(max_length=160)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name_plural = "rider inbox entries"


class DeliverySettings(models.Model):
    auto_assign = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        verbose_name_plural = "delivery settings"

    @classmethod
    def get(cls):
        return cls.objects.get_or_create(pk=1)[0]
