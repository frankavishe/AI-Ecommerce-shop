from django.contrib import admin

from .models import Delivery, DeliveryEvent, DeliveryNotification, DeliverySettings, RiderInboxEntry


class DeliveryEventInline(admin.TabularInline):
    model = DeliveryEvent
    extra = 0
    can_delete = False
    readonly_fields = ("status", "attempt", "rider", "actor_type", "actor", "note", "created_at")


@admin.register(Delivery)
class DeliveryAdmin(admin.ModelAdmin):
    list_display = ("order", "status", "rider", "attempt", "created_at")
    list_filter = ("status",)
    search_fields = ("order__number", "rider__phone")
    readonly_fields = ("order", "status", "rider", "attempt", "failure_reason", "assigned_at",
                       "picked_up_at", "delivered_at", "failed_at", "created_at", "updated_at")
    inlines = [DeliveryEventInline]


@admin.register(DeliveryNotification)
class DeliveryNotificationAdmin(admin.ModelAdmin):
    list_display = ("kind", "delivery", "rider", "attempt", "state", "created_at")
    list_filter = ("kind", "state")
    readonly_fields = ("delivery", "rider", "kind", "attempt", "outbound", "state", "created_at")


@admin.register(RiderInboxEntry)
class RiderInboxEntryAdmin(admin.ModelAdmin):
    list_display = ("rider", "kind", "title_en", "read_at", "created_at")
    list_filter = ("kind",)


@admin.register(DeliverySettings)
class DeliverySettingsAdmin(admin.ModelAdmin):
    list_display = ("auto_assign", "updated_at", "updated_by")
