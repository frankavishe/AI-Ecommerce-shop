from django.contrib import admin

from .models import Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ["reference", "order", "amount", "status", "collected_amount", "created_at"]
    list_filter = ["status", "channel"]
    search_fields = ["reference", "order__number", "provider_ref"]
    readonly_fields = [
        "order", "reference", "amount", "currency", "collected_amount",
        "provider_ref", "channel", "raw_payload", "created_at", "updated_at",
    ]
