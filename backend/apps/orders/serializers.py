from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.catalog.models import Product
from apps.payments.models import Payment

from .models import DeliveryRegion, Order, OrderEvent, OrderItem
from .services import normalize_phone

MONEY = {"max_digits": 12, "decimal_places": 2, "read_only": True}


class CartProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = ["id", "name", "slug", "price", "stock", "is_active"]


class CartLineSerializer(serializers.Serializer):
    product = CartProductSerializer()
    quantity = serializers.IntegerField()
    unit_price = serializers.DecimalField(**MONEY)
    line_total = serializers.DecimalField(**MONEY)


class CartSerializer(serializers.Serializer):
    """Renders services.cart_totals(cart)."""

    token = serializers.CharField()
    items = CartLineSerializer(many=True)
    item_count = serializers.IntegerField()
    subtotal = serializers.DecimalField(**MONEY)


class AddItemSerializer(serializers.Serializer):
    product_id = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1, default=1)


class SetQuantitySerializer(serializers.Serializer):
    quantity = serializers.IntegerField(min_value=0)


class MergeCartSerializer(serializers.Serializer):
    cart_token = serializers.CharField()


class CheckoutSerializer(serializers.Serializer):
    """Guest contact and address, or a saved address_id for logged-in customers.

    Prices and totals are never accepted from the client.
    """

    address_id = serializers.IntegerField(required=False)
    contact_name = serializers.CharField(max_length=120, required=False, allow_blank=True)
    contact_phone = serializers.CharField(max_length=20, required=False, allow_blank=True)
    region = serializers.CharField(max_length=80, required=False, allow_blank=True)
    district = serializers.CharField(max_length=80, required=False, allow_blank=True, default="")
    street = serializers.CharField(max_length=255, required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True, default="")

    def validate(self, attrs):
        user = self.context["request"].user
        if attrs.get("address_id") is not None:
            address = (
                user.addresses.filter(pk=attrs["address_id"]).first()
                if user.is_authenticated else None
            )
            if address is None:
                raise serializers.ValidationError({"address_id": "Unknown address."})
            attrs.update(region=address.region, district=address.district, street=address.street)
        if user.is_authenticated:
            attrs["contact_name"] = attrs.get("contact_name") or user.get_full_name() or user.username
            attrs["contact_phone"] = attrs.get("contact_phone") or user.phone or ""

        errors = {
            field: "This field is required."
            for field in ("contact_name", "contact_phone", "region", "street")
            if not (attrs.get(field) or "").strip()
        }
        if "contact_phone" not in errors:
            try:
                attrs["contact_phone"] = normalize_phone(attrs["contact_phone"])
            except DjangoValidationError as exc:
                errors["contact_phone"] = exc.messages
        if errors:
            raise serializers.ValidationError(errors)
        return attrs

    @property
    def contact(self):
        data = self.validated_data
        return {"name": data["contact_name"].strip(), "phone": data["contact_phone"]}

    @property
    def address(self):
        data = self.validated_data
        return {key: data[key].strip() for key in ("region", "district", "street", "notes")}


class OrderItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderItem
        fields = ["product", "product_name", "unit_price", "quantity", "line_total"]


class OrderEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderEvent
        fields = ["status", "source", "note", "created_at"]


class OrderSummarySerializer(serializers.ModelSerializer):
    currency = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = ["number", "status", "total", "currency", "placed_at", "paid_at"]

    def get_currency(self, obj) -> str:
        return settings.SHOP_CURRENCY


class OrderSerializer(OrderSummarySerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    events = OrderEventSerializer(many=True, read_only=True)
    payment_url = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            "number", "status", "contact_name", "contact_phone",
            "region", "district", "street", "notes",
            "subtotal", "delivery_fee", "total", "currency",
            "placed_at", "paid_at", "expires_at", "items", "events", "payment_url",
        ]
        read_only_fields = fields

    def get_payment_url(self, obj) -> str | None:
        if obj.status != Order.Status.AWAITING_PAYMENT:
            return None
        payment = (
            obj.payments.filter(status=Payment.Status.PENDING).exclude(checkout_link="")
            .order_by("-created_at", "-id").first()
        )
        return payment.checkout_link if payment else None


class DeliveryRegionSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeliveryRegion
        fields = ["name", "fee"]
