from django.contrib import admin

from apps.payments.models import Payment

from .models import DeliveryRegion, Order, OrderEvent, OrderItem

MONEY_FIELDS = ["subtotal", "delivery_fee", "total"]


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ["product", "product_name", "unit_price", "quantity", "line_total"]
    can_delete = False


class OrderEventInline(admin.TabularInline):
    model = OrderEvent
    extra = 0
    readonly_fields = ["status", "source", "actor", "note", "created_at"]
    can_delete = False


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    fields = ["reference", "amount", "status", "collected_amount", "channel", "created_at"]
    readonly_fields = fields
    can_delete = False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ["number", "contact_name", "contact_phone", "total", "status", "placed_at"]
    list_filter = ["status", "region"]
    search_fields = ["number", "contact_phone", "contact_name"]
    readonly_fields = MONEY_FIELDS + ["number", "placed_at", "paid_at", "stock_released"]
    inlines = [OrderItemInline, PaymentInline, OrderEventInline]


@admin.register(DeliveryRegion)
class DeliveryRegionAdmin(admin.ModelAdmin):
    list_display = ["name", "fee", "is_active"]
    list_editable = ["fee", "is_active"]
