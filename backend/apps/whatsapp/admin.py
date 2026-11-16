from django.contrib import admin

from .models import (
    WhatsAppContact,
    WhatsAppInboundMessage,
    WhatsAppLinkCode,
    WhatsAppOrderNotification,
    WhatsAppOutboundMessage,
)


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(WhatsAppContact)
class WhatsAppContactAdmin(ReadOnlyAdmin):
    list_display = ["phone", "profile_name", "user", "language", "updates_allowed", "last_inbound_at"]
    list_filter = ["language", "updates_allowed"]
    search_fields = ["phone", "wa_id", "profile_name", "user__username"]


@admin.register(WhatsAppInboundMessage)
class WhatsAppInboundMessageAdmin(ReadOnlyAdmin):
    list_display = ["wa_message_id", "contact", "type", "status", "error", "sent_at", "processed_at"]
    list_filter = ["status", "type"]
    search_fields = ["wa_message_id", "contact__phone", "text"]
    list_select_related = ["contact"]


@admin.register(WhatsAppOutboundMessage)
class WhatsAppOutboundMessageAdmin(ReadOnlyAdmin):
    list_display = ["id", "contact", "kind", "trigger", "status", "error_code", "attempts", "created_at"]
    list_filter = ["status", "kind", "trigger"]
    search_fields = ["wa_message_id", "contact__phone", "text"]
    list_select_related = ["contact"]


@admin.register(WhatsAppOrderNotification)
class WhatsAppOrderNotificationAdmin(ReadOnlyAdmin):
    list_display = ["order", "status", "state", "outbound", "created_at"]
    list_filter = ["state", "status"]
    search_fields = ["order__number"]
    list_select_related = ["order", "outbound"]


@admin.register(WhatsAppLinkCode)
class WhatsAppLinkCodeAdmin(ReadOnlyAdmin):
    list_display = ["user", "expires_at", "used_at", "used_by", "created_at"]
    exclude = ["code_hash"]  # never shown: it is enough to redeem a code
    search_fields = ["user__username"]
    list_select_related = ["user", "used_by"]
