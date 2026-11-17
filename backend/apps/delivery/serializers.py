"""Admin delivery API shapes (contracts/admin-api.md)."""

from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework import serializers

from apps.accounts.models import User

from .models import Delivery, DeliveryEvent, DeliveryNotification


def needs_attention(delivery):
    """Failed, or waiting longer than DELIVERY_WAITING_ALERT_MINUTES (FR-023)."""
    if delivery.status == Delivery.Status.FAILED:
        return True
    limit = timezone.now() - timedelta(minutes=settings.DELIVERY_WAITING_ALERT_MINUTES)
    return delivery.status == Delivery.Status.WAITING and delivery.created_at < limit


def full_name(user):
    return (user.get_full_name() or user.username) if user else None


class RiderBriefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.SerializerMethodField()
    phone = serializers.CharField()
    vehicle = serializers.SerializerMethodField()

    def get_name(self, obj) -> str:
        return full_name(obj)

    def get_vehicle(self, obj) -> str | None:
        profile = getattr(obj, "rider_profile", None)
        return profile.vehicle if profile else None


class DeliveryOrderSerializer(serializers.Serializer):
    number = serializers.CharField()
    region = serializers.CharField()
    street = serializers.CharField()
    contact_name = serializers.CharField()
    item_count = serializers.SerializerMethodField()
    total = serializers.DecimalField(max_digits=12, decimal_places=2)
    paid_at = serializers.DateTimeField(allow_null=True)
    status = serializers.CharField()

    def get_item_count(self, obj) -> int:
        return sum(item.quantity for item in obj.items.all())


class DeliveryListSerializer(serializers.ModelSerializer):
    attention = serializers.SerializerMethodField()
    order = DeliveryOrderSerializer(read_only=True)
    rider = RiderBriefSerializer(read_only=True, allow_null=True)

    class Meta:
        model = Delivery
        fields = ["id", "status", "attempt", "attention", "order", "rider", "created_at", "updated_at"]
        read_only_fields = fields

    def get_attention(self, obj) -> bool:
        annotated = getattr(obj, "attention", None)  # the list queryset annotates it for sorting
        return annotated if annotated is not None else needs_attention(obj)


class DeliveryEventSerializer(serializers.ModelSerializer):
    rider = serializers.SerializerMethodField()
    actor_name = serializers.SerializerMethodField()

    class Meta:
        model = DeliveryEvent
        fields = ["status", "attempt", "rider", "actor_type", "actor_name", "note", "created_at"]
        read_only_fields = fields

    def get_rider(self, obj) -> str | None:
        return full_name(obj.rider)

    def get_actor_name(self, obj) -> str | None:
        return full_name(obj.actor)


class DeliveryNotificationSerializer(serializers.ModelSerializer):
    outbound_status = serializers.SerializerMethodField()

    class Meta:
        model = DeliveryNotification
        fields = ["kind", "attempt", "state", "outbound_status", "created_at"]
        read_only_fields = fields

    def get_outbound_status(self, obj) -> str | None:
        return obj.outbound.status if obj.outbound_id else None


class DeliveryDetailSerializer(DeliveryListSerializer):
    events = DeliveryEventSerializer(many=True, read_only=True)
    notifications = DeliveryNotificationSerializer(many=True, read_only=True)

    class Meta(DeliveryListSerializer.Meta):
        fields = DeliveryListSerializer.Meta.fields + ["events", "notifications", "failure_reason"]
        read_only_fields = fields


class CandidateSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.SerializerMethodField()
    phone = serializers.CharField()
    vehicle = serializers.CharField(source="rider_profile.vehicle")
    regions = serializers.SerializerMethodField()
    is_available = serializers.BooleanField(source="rider_profile.is_available")
    open_jobs = serializers.IntegerField()
    covers_region = serializers.BooleanField()

    def get_name(self, obj) -> str:
        return full_name(obj)

    def get_regions(self, obj) -> list[str]:
        return [region.name for region in obj.rider_profile.regions.all()]


class AssignSerializer(serializers.Serializer):
    rider = serializers.PrimaryKeyRelatedField(queryset=User.objects.filter(role=User.Role.RIDER))
    expected_status = serializers.ChoiceField(choices=Delivery.Status.choices, required=False, allow_null=True)
    expected_rider = serializers.IntegerField(required=False, allow_null=True)


class UnassignSerializer(serializers.Serializer):
    expected_rider = serializers.IntegerField(required=False, allow_null=True)


class StatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["picked_up", "on_the_way", "delivered", "failed"])
    note = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    expected_status = serializers.ChoiceField(choices=Delivery.Status.choices, required=False, allow_null=True)
