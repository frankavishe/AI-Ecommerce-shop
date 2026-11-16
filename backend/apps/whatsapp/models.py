"""WhatsApp channel data (specs/004-whatsapp-channel/data-model.md).

Money is never stored here except the display-only prompt total: amounts come from orders.Order
and catalog.Product.
"""

import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

WINDOW = timedelta(hours=24)


class Language(models.TextChoices):
    SWAHILI = "sw", "Swahili"
    ENGLISH = "en", "English"


class WhatsAppContact(models.Model):
    wa_id = models.CharField(max_length=20, unique=True)
    phone = models.CharField(max_length=16, unique=True)
    profile_name = models.CharField(max_length=120, blank=True)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="whatsapp_contact",
    )
    linked_at = models.DateTimeField(null=True, blank=True)
    conversation = models.ForeignKey(
        "ai.Conversation", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    language = models.CharField(max_length=2, choices=Language.choices, default=Language.SWAHILI)
    updates_allowed = models.BooleanField(default=True)
    last_inbound_at = models.DateTimeField(null=True, blank=True)
    slowdown_notice_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.phone

    @property
    def window_open(self):
        return self.last_inbound_at is not None and timezone.now() - self.last_inbound_at < WINDOW

    @property
    def window_closes_at(self):
        return self.last_inbound_at + WINDOW if self.last_inbound_at else None


class WhatsAppInboundMessage(models.Model):
    class Type(models.TextChoices):
        TEXT = "text", "Text"
        IMAGE = "image", "Image"
        AUDIO = "audio", "Audio"
        BUTTON = "button", "Button"
        UNSUPPORTED = "unsupported", "Unsupported"

    class Status(models.TextChoices):
        RECEIVED = "received", "Received"
        PROCESSING = "processing", "Processing"
        ANSWERED = "answered", "Answered"
        RECORDED = "recorded", "Recorded"
        REJECTED = "rejected", "Rejected"
        FAILED = "failed", "Failed"
        RATE_LIMITED = "rate_limited", "Rate limited"

    wa_message_id = models.CharField(max_length=128, unique=True)
    contact = models.ForeignKey(WhatsAppContact, on_delete=models.CASCADE, related_name="inbound")
    type = models.CharField(max_length=16, choices=Type.choices)
    raw_type = models.CharField(max_length=32)
    sent_at = models.DateTimeField()
    received_at = models.DateTimeField(auto_now_add=True)
    text = models.TextField(blank=True)
    button_id = models.CharField(max_length=256, blank=True)
    media_id = models.CharField(max_length=128, blank=True)
    media_mime = models.CharField(max_length=64, blank=True)
    media = models.FileField(upload_to="whatsapp/audio/%Y/%m/", null=True, blank=True)
    transcript = models.TextField(blank=True)
    transcript_language = models.CharField(max_length=8, blank=True)
    duration_s = models.FloatField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.RECEIVED)
    error = models.CharField(max_length=64, blank=True)
    chat_message = models.ForeignKey(
        "ai.ChatMessage", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["contact", "status", "sent_at", "id"], name="wa_inbound_queue"),
            models.Index(fields=["contact", "received_at"], name="wa_inbound_rate"),
        ]

    def __str__(self):
        return self.wa_message_id


class WhatsAppOutboundMessage(models.Model):
    class Kind(models.TextChoices):
        TEXT = "text", "Text"
        IMAGE = "image", "Image"
        BUTTONS = "buttons", "Buttons"
        TEMPLATE = "template", "Template"

    class Trigger(models.TextChoices):
        ASSISTANT = "assistant", "Assistant"
        STAFF = "staff", "Staff"
        SYSTEM = "system", "System"
        ORDER_UPDATE = "order_update", "Order update"
        PAYMENT = "payment", "Payment"

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        SENT = "sent", "Sent"
        DELIVERED = "delivered", "Delivered"
        READ = "read", "Read"
        FAILED = "failed", "Failed"
        SKIPPED = "skipped", "Skipped"

    contact = models.ForeignKey(WhatsAppContact, on_delete=models.CASCADE, related_name="outbound")
    conversation = models.ForeignKey(
        "ai.Conversation", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    kind = models.CharField(max_length=16, choices=Kind.choices)
    trigger = models.CharField(max_length=16, choices=Trigger.choices)
    body = models.JSONField(default=dict)
    text = models.TextField(blank=True)
    batch = models.UUIDField(default=uuid.uuid4)
    position = models.SmallIntegerField(default=0)
    wa_message_id = models.CharField(max_length=128, unique=True, null=True, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.QUEUED)
    status_at = models.DateTimeField(null=True, blank=True)
    attempts = models.SmallIntegerField(default=0)
    error_code = models.CharField(max_length=16, blank=True)
    error = models.TextField(blank=True)
    staff_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["batch", "position"], name="wa_outbound_batch")]
        ordering = ["-created_at", "-id"]


class WhatsAppOrder(models.Model):
    order = models.OneToOneField(
        "orders.Order", primary_key=True, on_delete=models.CASCADE, related_name="whatsapp"
    )
    contact = models.ForeignKey(WhatsAppContact, on_delete=models.CASCADE, related_name="orders")
    created_at = models.DateTimeField(auto_now_add=True)


class WhatsAppOrderNotification(models.Model):
    class State(models.TextChoices):
        SENDING = "sending", "Sending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"
        SKIPPED = "skipped", "Skipped"

    order = models.ForeignKey("orders.Order", on_delete=models.CASCADE, related_name="+")
    status = models.CharField(max_length=20)
    outbound = models.ForeignKey(
        WhatsAppOutboundMessage, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    state = models.CharField(max_length=10, choices=State.choices, default=State.SENDING)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["order", "status"], name="wa_notification_order_status")
        ]


class WhatsAppCheckoutPrompt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey("ai.Conversation", on_delete=models.CASCADE, related_name="+")
    contact = models.ForeignKey(WhatsAppContact, on_delete=models.CASCADE, related_name="+")
    fingerprint = models.CharField(max_length=64)
    method = models.CharField(max_length=16)
    network = models.CharField(max_length=16, blank=True)
    total = models.DecimalField(max_digits=12, decimal_places=2)  # display only, never charged
    order = models.ForeignKey(
        "orders.Order", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)


class WhatsAppLinkCode(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    code_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    used_by = models.ForeignKey(
        WhatsAppContact, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)


class WhatsAppLinkAttempt(models.Model):
    contact = models.ForeignKey(WhatsAppContact, on_delete=models.CASCADE, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)


class WhatsAppMediaUpload(models.Model):
    product_image = models.OneToOneField(
        "catalog.ProductImage", primary_key=True, on_delete=models.CASCADE, related_name="+"
    )
    media_id = models.CharField(max_length=128)
    uploaded_at = models.DateTimeField()
