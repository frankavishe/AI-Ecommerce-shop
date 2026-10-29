"""Order business rules. Views, Celery tasks and (later) the WhatsApp agent all call these."""

import re
import secrets
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.accounts.models import phone_validator
from apps.catalog.models import Product

from .models import Cart, CartItem, DeliveryRegion, Order, OrderEvent, OrderItem

ORDER_NUMBER_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

S = Order.Status
TRANSITIONS = {
    S.AWAITING_PAYMENT: {S.PAID, S.CANCELLED, S.EXPIRED, S.NEEDS_REVIEW},
    S.PAID: {S.PROCESSING, S.CANCELLED, S.NEEDS_REVIEW},
    S.PROCESSING: {S.OUT_FOR_DELIVERY, S.CANCELLED},
    S.OUT_FOR_DELIVERY: {S.DELIVERED, S.CANCELLED},
    S.NEEDS_REVIEW: {S.PAID, S.CANCELLED},
    S.EXPIRED: {S.NEEDS_REVIEW},
    S.DELIVERED: set(),
    S.CANCELLED: set(),
}
STOCK_RELEASING = {S.CANCELLED, S.EXPIRED}
GUEST_CART_LIFETIME = timedelta(days=30)


class ShopError(Exception):
    code = "error"
    status_code = 400

    def __init__(self, detail, **extra):
        super().__init__(detail)
        self.detail = detail
        self.extra = extra


class InvalidTransition(ShopError):
    code = "invalid_transition"


class OutOfStock(ShopError):
    code = "out_of_stock"


class InactiveProduct(ShopError):
    code = "inactive_product"


class EmptyCart(ShopError):
    code = "empty_cart"


class ProductNotFound(ShopError):
    code = "product_not_found"
    status_code = 404


class LineNotFound(ShopError):
    code = "not_in_cart"
    status_code = 404


def normalize_phone(raw):
    """Return an E.164 number; Tanzanian local numbers (0XXXXXXXXX) become +255XXXXXXXXX."""
    phone = re.sub(r"[\s\-()]", "", str(raw or ""))
    if re.fullmatch(r"0\d{9}", phone):
        phone = "+255" + phone[1:]
    elif re.fullmatch(r"255\d{9}", phone):
        phone = "+" + phone
    phone_validator(phone)
    return phone


def delivery_fee_for(region_name):
    region = DeliveryRegion.objects.filter(
        name__iexact=(region_name or "").strip(), is_active=True
    ).first()
    return region.fee if region else settings.SHOP_DEFAULT_DELIVERY_FEE


def generate_order_number():
    while True:
        number = "".join(secrets.choice(ORDER_NUMBER_ALPHABET) for _ in range(8))
        if not Order.objects.filter(number=number).exists():
            return number


def release_stock(order):
    """Return the order's units to stock exactly once."""
    if order.stock_released:
        return
    for item in order.items.exclude(product=None).order_by("product_id"):
        Product.objects.filter(pk=item.product_id).update(stock=F("stock") + item.quantity)
    order.stock_released = True
    order.save(update_fields=["stock_released"])


def transition(order, status, source, actor=None, note=""):
    if status not in TRANSITIONS.get(order.status, set()):
        raise InvalidTransition(f"Cannot move an order from {order.status} to {status}.")
    with transaction.atomic():
        order.status = status
        fields = ["status"]
        if status == S.PAID and order.paid_at is None:
            order.paid_at = timezone.now()
            fields.append("paid_at")
        order.save(update_fields=fields)
        if status in STOCK_RELEASING:
            release_stock(order)
        OrderEvent.objects.create(order=order, status=status, source=source, actor=actor, note=note)
    return order


# --- Cart -------------------------------------------------------------------------------------


def get_or_create_cart(request):
    """The user's cart, the guest cart named by X-Cart-Token, or a new guest cart."""
    user = request.user
    if user.is_authenticated:
        return Cart.objects.get_or_create(user=user)[0]
    token = request.headers.get("X-Cart-Token")
    if token:
        cart = Cart.objects.filter(
            token=token, user=None, updated_at__gte=timezone.now() - GUEST_CART_LIFETIME
        ).first()
        if cart:
            return cart
    return Cart.objects.create()


def _touch(cart):
    cart.save(update_fields=["updated_at"])


def _sellable(product_id):
    product = Product.objects.filter(pk=product_id).first()
    if product is None:
        raise ProductNotFound("Product not found.")
    if not product.is_active:
        raise InactiveProduct(f"{product.name} is no longer available.", product=product.id)
    return product


def _check_stock(product, quantity):
    if quantity > product.stock:
        raise OutOfStock(
            f"Only {product.stock} of {product.name} available.",
            product=product.id, available=product.stock,
        )


def add_item(cart, product_id, quantity=1):
    product = _sellable(product_id)
    line = cart.items.filter(product=product).first()
    total = quantity + (line.quantity if line else 0)
    _check_stock(product, total)
    if line:
        line.quantity = total
        line.save(update_fields=["quantity"])
    else:
        CartItem.objects.create(cart=cart, product=product, quantity=total)
    _touch(cart)
    return cart


def set_quantity(cart, product_id, quantity):
    if quantity <= 0:
        return remove_item(cart, product_id)
    line = cart.items.filter(product_id=product_id).first()
    if line is None:
        raise LineNotFound("This product is not in the cart.")
    product = _sellable(product_id)
    _check_stock(product, quantity)
    line.quantity = quantity
    line.save(update_fields=["quantity"])
    _touch(cart)
    return cart


def remove_item(cart, product_id):
    cart.items.filter(product_id=product_id).delete()
    _touch(cart)
    return cart


def clear(cart):
    cart.items.all().delete()
    _touch(cart)
    return cart


def cart_totals(cart):
    lines = []
    for item in cart.items.select_related("product"):
        price = item.product.price
        lines.append({
            "product": item.product,
            "quantity": item.quantity,
            "unit_price": price,
            "line_total": price * item.quantity,
        })
    return {
        "token": cart.token,
        "items": lines,
        "item_count": sum(line["quantity"] for line in lines),
        "subtotal": sum((line["line_total"] for line in lines), Decimal("0")),
    }


def merge_carts(user_cart, guest_cart):
    """Move a guest cart into the user's cart, capping each line at the available stock."""
    if guest_cart.pk == user_cart.pk:
        return user_cart
    with transaction.atomic():
        for item in guest_cart.items.select_related("product"):
            line, created = CartItem.objects.get_or_create(
                cart=user_cart, product=item.product, defaults={"quantity": item.quantity}
            )
            if not created:
                line.quantity += item.quantity
            line.quantity = min(line.quantity, item.product.stock)
            if line.quantity > 0:
                line.save(update_fields=["quantity"])
            else:
                line.delete()
        guest_cart.delete()
        _touch(user_cart)
    return user_cart


# --- Orders -----------------------------------------------------------------------------------


def place_order(cart, contact, address, user=None):
    """Turn a cart into an order awaiting payment. Stock is taken here, atomically (research R7).

    contact: {"name", "phone"}; address: {"region", "street", "district"?, "notes"?}.
    """
    items = list(cart.items.select_related("product").order_by("product_id"))
    if not items:
        raise EmptyCart("Your cart is empty.")
    with transaction.atomic():
        for item in items:
            product = item.product
            if not product.is_active:
                raise InactiveProduct(f"{product.name} is no longer available.", product=product.id)
            taken = Product.objects.filter(
                pk=product.pk, stock__gte=item.quantity, is_active=True
            ).update(stock=F("stock") - item.quantity)
            if not taken:
                product.refresh_from_db(fields=["stock"])
                _check_stock(product, item.quantity)
                raise OutOfStock(f"{product.name} is out of stock.", product=product.id, available=0)

        subtotal = sum((i.product.price * i.quantity for i in items), Decimal("0"))
        fee = delivery_fee_for(address["region"])
        now = timezone.now()
        order = Order.objects.create(
            number=generate_order_number(),
            user=user,
            contact_name=contact["name"],
            contact_phone=contact["phone"],
            region=address["region"],
            district=address.get("district", ""),
            street=address["street"],
            notes=address.get("notes", ""),
            subtotal=subtotal,
            delivery_fee=fee,
            total=subtotal + fee,
            placed_at=now,
            expires_at=now + timedelta(minutes=settings.ORDER_EXPIRY_MINUTES),
        )
        OrderItem.objects.bulk_create([
            OrderItem(
                order=order, product=i.product, product_name=i.product.name,
                unit_price=i.product.price, quantity=i.quantity,
                line_total=i.product.price * i.quantity,
            )
            for i in items
        ])
        OrderEvent.objects.create(
            order=order, status=order.status, actor=user, source=OrderEvent.Source.CUSTOMER
        )
        cart.items.all().delete()
    return order
