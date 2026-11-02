from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import generics, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsShopAdmin
from apps.payments.models import Payment
from apps.payments.services import start_payment

from . import services
from .filters import OrderFilter, OrderSearchFilter
from .models import Cart, DeliveryRegion, Order, OrderEvent
from .serializers import (
    AddItemSerializer,
    AdminDeliveryRegionSerializer,
    AdminOrderSerializer,
    AdminOrderSummarySerializer,
    CartSerializer,
    CheckoutSerializer,
    DeliveryRegionSerializer,
    MergeCartSerializer,
    OrderLookupSerializer,
    OrderSerializer,
    OrderSummarySerializer,
    PayOrderSerializer,
    SetQuantitySerializer,
    StatusChangeSerializer,
)

CART_TOKEN = OpenApiParameter(
    "X-Cart-Token", str, OpenApiParameter.HEADER, required=False,
    description="Guest cart token returned in the cart body.",
)


class ShopErrorMixin:
    """Render service-layer ShopErrors as {"detail", "code", ...extra}."""

    def handle_exception(self, exc):
        if isinstance(exc, services.ShopError):
            return Response(
                {"detail": exc.detail, "code": exc.code, **exc.extra}, status=exc.status_code
            )
        return super().handle_exception(exc)


def cart_response(cart):
    return Response(CartSerializer(services.cart_totals(cart)).data)


@extend_schema(parameters=[CART_TOKEN])
class CartView(ShopErrorMixin, APIView):
    @extend_schema(responses=CartSerializer)
    def get(self, request):
        return cart_response(services.get_or_create_cart(request))

    @extend_schema(responses={204: None})
    def delete(self, request):
        services.clear(services.get_or_create_cart(request))
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(parameters=[CART_TOKEN], request=AddItemSerializer, responses=CartSerializer)
class CartItemsView(ShopErrorMixin, APIView):
    def post(self, request):
        data = AddItemSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        cart = services.get_or_create_cart(request)
        services.add_item(cart, data.validated_data["product_id"], data.validated_data["quantity"])
        return cart_response(cart)


@extend_schema(parameters=[CART_TOKEN], responses=CartSerializer)
class CartItemDetailView(ShopErrorMixin, APIView):
    @extend_schema(request=SetQuantitySerializer)
    def patch(self, request, product_id):
        data = SetQuantitySerializer(data=request.data)
        data.is_valid(raise_exception=True)
        cart = services.get_or_create_cart(request)
        services.set_quantity(cart, product_id, data.validated_data["quantity"])
        return cart_response(cart)

    def delete(self, request, product_id):
        cart = services.get_or_create_cart(request)
        services.remove_item(cart, product_id)
        return cart_response(cart)


@extend_schema(request=MergeCartSerializer, responses=CartSerializer)
class CartMergeView(ShopErrorMixin, APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        data = MergeCartSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        guest = get_object_or_404(Cart, token=data.validated_data["cart_token"], user=None)
        cart = services.merge_carts(services.get_or_create_cart(request), guest)
        return cart_response(cart)


MOBILE_MONEY_PROMPT = "Check your phone and enter your mobile money PIN to pay."


def payment_message(payment):
    if payment is None:
        return None
    if payment.status == Payment.Status.SUCCESS:
        return "Payment received. Thank you!"
    if payment.method == Payment.Method.MOBILE_MONEY:
        return MOBILE_MONEY_PROMPT
    return "Continue to the card payment page to pay."


def order_with_payment(order, payment=None, payment_error=None):
    order.refresh_from_db()
    data = OrderSerializer(order).data
    data["payment_method"] = payment.method if payment else None
    data["payment_message"] = payment_message(payment)
    if payment_error:
        data["payment_error"] = payment_error.message
        data["payment_error_code"] = payment_error.code
    return data


@extend_schema(
    parameters=[CART_TOKEN], request=CheckoutSerializer, responses={201: OrderSerializer}
)
class CheckoutView(ShopErrorMixin, APIView):
    def post(self, request):
        checkout = CheckoutSerializer(data=request.data, context={"request": request})
        checkout.is_valid(raise_exception=True)
        cart = services.get_or_create_cart(request)
        user = request.user if request.user.is_authenticated else None
        order = services.place_order(cart, checkout.contact, checkout.address, user=user)
        payment, error = start_payment(order, **checkout.payment)
        return Response(order_with_payment(order, payment, error), status=status.HTTP_201_CREATED)


@extend_schema(responses=inline_serializer("DeliveryRegions", {
    "regions": DeliveryRegionSerializer(many=True),
    "default_fee": serializers.DecimalField(max_digits=12, decimal_places=2),
}))
class DeliveryRegionListView(APIView):
    def get(self, request):
        regions = DeliveryRegion.objects.filter(is_active=True)
        return Response({
            "regions": DeliveryRegionSerializer(regions, many=True).data,
            "default_fee": f"{settings.SHOP_DEFAULT_DELIVERY_FEE:.2f}",
        })


class OrderListView(generics.ListAPIView):
    serializer_class = OrderSummarySerializer
    permission_classes = [IsAuthenticated]
    filter_backends = []

    def get_queryset(self):
        return Order.objects.filter(user=self.request.user)


class OrderDetailView(generics.RetrieveAPIView):
    serializer_class = OrderSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = "number"

    def get_queryset(self):
        return Order.objects.filter(user=self.request.user).prefetch_related("items", "events")


def order_for_phone(number, raw_phone):
    """Guest access: the order number plus the checkout phone, or a 404 either way."""
    try:
        phone = services.normalize_phone(raw_phone)
    except DjangoValidationError:
        raise Http404
    return get_object_or_404(Order, number=str(number).strip().upper(), contact_phone=phone)


@extend_schema(request=OrderLookupSerializer, responses=OrderSerializer)
class OrderLookupView(APIView):
    def post(self, request):
        data = OrderLookupSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        order = order_for_phone(data.validated_data["number"], data.validated_data["phone"])
        return Response(OrderSerializer(order).data)


@extend_schema(
    request=PayOrderSerializer,
    responses=inline_serializer("PaymentStarted", {
        "payment_method": serializers.ChoiceField(choices=Payment.Method.choices),
        "payment_status": serializers.ChoiceField(choices=Payment.Status.choices),
        "payment_url": serializers.URLField(allow_null=True),
        "message": serializers.CharField(),
    }),
)
class OrderPayView(APIView):
    """Start a fresh payment attempt (new reference) for an order still awaiting payment.

    Card: returns payment_url to redirect to. Mobile money: payment_url is null and the customer
    approves the prompt on their phone.
    """

    def post(self, request, number):
        data = PayOrderSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        user = request.user
        if user.is_authenticated and Order.objects.filter(number=number, user=user).exists():
            order = Order.objects.get(number=number)
        elif data.validated_data.get("phone"):
            order = order_for_phone(number, data.validated_data["phone"])
        else:
            raise Http404
        if order.status != Order.Status.AWAITING_PAYMENT:
            return Response(
                {"detail": "This order is not awaiting payment.", "code": "not_awaiting_payment"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        payment, error = start_payment(order, **data.payment)
        if payment is None:
            code = (
                status.HTTP_503_SERVICE_UNAVAILABLE if error.code == "payment_unavailable"
                else status.HTTP_400_BAD_REQUEST
            )
            return Response({"detail": error.message, "code": error.code}, status=code)
        return Response({
            "payment_method": payment.method,
            "payment_status": payment.status,
            "payment_url": payment.checkout_link or None,
            "message": payment_message(payment),
        })


class AdminOrderViewSet(ShopErrorMixin, viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsShopAdmin]
    lookup_field = "number"
    filter_backends = [DjangoFilterBackend, OrderSearchFilter]
    filterset_class = OrderFilter
    search_fields = ["number", "contact_phone", "contact_name"]

    def get_queryset(self):
        qs = Order.objects.all()
        if self.action == "list":
            return qs
        return qs.select_related("user").prefetch_related("items", "events__actor", "payments")

    def get_serializer_class(self):
        return AdminOrderSummarySerializer if self.action == "list" else AdminOrderSerializer

    @extend_schema(request=StatusChangeSerializer, responses=AdminOrderSerializer)
    @action(detail=True, methods=["post"])
    def status(self, request, number=None):
        change = StatusChangeSerializer(data=request.data)
        change.is_valid(raise_exception=True)
        order = self.get_object()
        services.transition(
            order, change.validated_data["status"], OrderEvent.Source.ADMIN,
            actor=request.user, note=change.validated_data["note"],
        )
        return Response(AdminOrderSerializer(self.get_queryset().get(pk=order.pk)).data)


class AdminDeliveryRegionViewSet(viewsets.ModelViewSet):
    permission_classes = [IsShopAdmin]
    serializer_class = AdminDeliveryRegionSerializer
    queryset = DeliveryRegion.objects.all()
    filter_backends = []
