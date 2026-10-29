from django.db import models

from apps.orders.models import Order


class Payment(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"
        MISMATCH = "mismatch", "Amount mismatch"

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="payments")
    reference = models.CharField(max_length=20, unique=True, help_text="ClickPesa orderReference")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="TZS")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    checkout_link = models.URLField(max_length=500, blank=True)
    provider_ref = models.CharField(max_length=100, blank=True)
    channel = models.CharField(max_length=60, blank=True)
    collected_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    raw_payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"Payment {self.reference} ({self.status})"
