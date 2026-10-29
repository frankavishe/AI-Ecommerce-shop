from django.conf import settings
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.payments.services import start_payment

from . import services
from .models import DeliveryRegion
from .serializers import (
    AddItemSerializer,
    CartSerializer,
    CheckoutSerializer,
    DeliveryRegionSerializer,
    OrderSerializer,
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
