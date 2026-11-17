"""Admin delivery API (contracts/admin-api.md). Every write goes through services.change()."""

from datetime import timedelta

from django.conf import settings
from django.db.models import BooleanField, Case, Exists, OuterRef, Value, When
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status as http
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsShopAdmin
from apps.orders.models import DeliveryRegion, Order
from apps.orders.views import ShopErrorMixin

from . import riders, services
from .models import Delivery
from .serializers import (
    AssignSerializer,
    CandidateSerializer,
    DeliveryDetailSerializer,
    DeliveryListSerializer,
    StatusSerializer,
    UnassignSerializer,
)

S = Delivery.Status


def detail_queryset():
    return Delivery.objects.select_related("order", "rider__rider_profile").prefetch_related(
        "order__items", "events__rider", "events__actor", "notifications__outbound",
    )


def detail_response(delivery, status=http.HTTP_200_OK):
    return Response(DeliveryDetailSerializer(detail_queryset().get(pk=delivery.pk)).data, status=status)


class DeliveryErrorMixin(ShopErrorMixin):
    def handle_exception(self, exc):
        if isinstance(exc, services.StaleDelivery):
            return Response({"detail": exc.detail, "code": exc.code,
                             "delivery": DeliveryDetailSerializer(detail_queryset().get(pk=exc.delivery.pk)).data},
                            status=exc.status_code)
        return super().handle_exception(exc)


def expectations(data, rider_field="expected_rider"):
    expect = {}
    if data.get("expected_status"):
        expect["status"] = data["expected_status"]
    if rider_field in data:  # null means "nobody was assigned"
        expect["rider"] = data[rider_field]
    return expect


LIST_FILTERS = [
    OpenApiParameter("status", OpenApiTypes.STR, many=True, enum=S.values),
    OpenApiParameter("region", OpenApiTypes.STR),
    OpenApiParameter("rider", OpenApiTypes.INT),
    OpenApiParameter("attention", OpenApiTypes.BOOL),
]


@extend_schema(tags=["admin-deliveries"])
class AdminDeliveryViewSet(DeliveryErrorMixin, viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsShopAdmin]
    filter_backends = []

    def get_queryset(self):
        limit = timezone.now() - timedelta(minutes=settings.DELIVERY_WAITING_ALERT_MINUTES)
        qs = detail_queryset().annotate(attention=Case(
            When(status=S.FAILED, then=Value(True)),
            When(status=S.WAITING, created_at__lt=limit, then=Value(True)),
            default=Value(False), output_field=BooleanField(),
        ))
        params = self.request.query_params
        if statuses := params.getlist("status"):
            qs = qs.filter(status__in=statuses)
        if region := params.get("region"):
            qs = qs.filter(order__region=region)
        if rider := params.get("rider"):
            qs = qs.filter(rider_id=rider) if rider.isdigit() else qs.none()
        if params.get("attention") in ("1", "true", "True"):
            qs = qs.filter(attention=True)
        return qs.order_by("-attention", "created_at", "id")

    def get_serializer_class(self):
        return DeliveryListSerializer if self.action == "list" else DeliveryDetailSerializer

    @extend_schema(parameters=LIST_FILTERS)
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(responses=CandidateSerializer(many=True))
    @action(detail=True, methods=["get"])
    def candidates(self, request, pk=None):
        """Riders for the assign dialog (FR-007): region riders first, then the least busy."""
        delivery = self.get_object()
        covers = DeliveryRegion.objects.filter(riders__user=OuterRef("pk"), name=delivery.order.region)
        qs = riders.annotate_open_jobs(riders.active_riders()).annotate(covers_region=Exists(covers))
        qs = qs.select_related("rider_profile").prefetch_related("rider_profile__regions").order_by(
            "-covers_region", "-rider_profile__is_available", "open_jobs", "first_name", "id")
        return Response(CandidateSerializer(qs, many=True).data)

    @extend_schema(request=AssignSerializer, responses=DeliveryDetailSerializer)
    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        data = AssignSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        delivery = self.get_object()
        services.assign(delivery, data.validated_data["rider"], request.user, expect=expectations(request.data))
        return detail_response(delivery)

    @extend_schema(request=UnassignSerializer, responses=DeliveryDetailSerializer)
    @action(detail=True, methods=["post"])
    def unassign(self, request, pk=None):
        data = UnassignSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        delivery = self.get_object()
        services.unassign(delivery, request.user, expect=expectations(request.data))
        return detail_response(delivery)

    @extend_schema(request=StatusSerializer, responses=DeliveryDetailSerializer)
    @action(detail=True, methods=["post"])
    def status(self, request, pk=None):
        """Admin override when the rider can't use the phone."""
        data = StatusSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        delivery = self.get_object()
        services.change(delivery, data.validated_data["status"], request.user, actor_type="admin",
                        note=data.validated_data["note"], expect=expectations(data.validated_data))
        return detail_response(delivery)


class CreateDeliveryView(ShopErrorMixin, APIView):
    """FR-005: a delivery for an order paid before this feature existed."""

    permission_classes = [IsShopAdmin]

    @extend_schema(request=None, responses={201: DeliveryDetailSerializer}, tags=["admin-deliveries"])
    def post(self, request, number):
        order = get_object_or_404(Order, number=number)
        if Delivery.objects.filter(order=order).exists():
            return Response({"detail": "This order already has a delivery.", "code": "exists"}, status=409)
        if order.status not in services.DELIVERABLE:
            return Response({"detail": "Only paid or processing orders can be delivered.",
                             "code": "not_deliverable"}, status=400)
        delivery, _ = services.create_for_order(order)
        return detail_response(delivery, status=http.HTTP_201_CREATED)

