from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import generics, serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.payments.services import start_payment

from . import services
from .models import Cart, DeliveryRegion, Order
from .serializers import (
    AddItemSerializer,
    CartSerializer,
    CheckoutSerializer,
    DeliveryRegionSerializer,
    MergeCartSerializer,
    OrderLookupSerializer,
    OrderSerializer,
    OrderSummarySerializer,
    PayOrderSerializer,
    SetQuantitySerializer,
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


def order_with_payment(order, payment_error=None):
    data = OrderSerializer(order).data
    if payment_error:
        data["payment_error"] = payment_error
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
        _, error = start_payment(order)
        return Response(order_with_payment(order, error), status=status.HTTP_201_CREATED)


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
    responses=inline_serializer("PaymentLink", {"payment_url": serializers.URLField()}),
)
class OrderPayView(APIView):
    """Issue a fresh checkout link (new reference) for an order still awaiting payment."""

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
        payment, error = start_payment(order)
        if payment is None:
            return Response(
                {"detail": error, "code": "payment_unavailable"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response({"payment_url": payment.checkout_link})
