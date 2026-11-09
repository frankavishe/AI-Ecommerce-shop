from django.db import models

from apps.orders.models import Order


class Payment(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"
        MISMATCH = "mismatch", "Amount mismatch"

    class Method(models.TextChoices):
        MOBILE_MONEY = "mobile_money", "Mobile money"
        CARD = "card", "Card"

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="payments")
    reference = models.CharField(max_length=20, unique=True, help_text="Our reference, sent to Stakaba as metadata.orderId")
    method = models.CharField(max_length=12, choices=Method.choices, default=Method.MOBILE_MONEY)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="TZS")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    checkout_link = models.URLField(max_length=500, blank=True)
    provider_ref = models.CharField(
        max_length=100, blank=True, db_index=True, help_text="Stakaba internalReference"
    )
    channel = models.CharField(max_length=60, blank=True, help_text="Mobile money network")
    receipt = models.CharField(
        max_length=100, blank=True, help_text="Operator receipt (providerReference), quoted in disputes"
    )
    collected_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    raw_payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"Payment {self.reference} ({self.status})"
