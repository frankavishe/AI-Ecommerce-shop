"""Assistant tools (specs/003-ai-core/contracts/agent-tools.md).

The model only sees the tools for its role, and every call is checked again here: unknown tools,
tools for another role, extra or wrongly-typed arguments are refused before anything runs. Each
tool runs in its own transaction, so a failure never leaves a half-applied change. Prices always
come from the database; no tool takes a price from the model.
"""

import json
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.db import transaction
from django.http import Http404
from django.utils import timezone

from apps.catalog.models import Product
from apps.orders import services
from apps.orders.models import Cart, Order
from apps.orders.serializers import CartSerializer, CheckoutSerializer
from apps.orders.services import ShopError
from apps.orders.views import order_for_phone, payment_message
from apps.payments.models import Payment
from apps.payments.services import check_payment_options, start_payment
from apps.payments.stakaba import NETWORKS

from . import search

GUEST, CUSTOMER = "guest", "customer"
ALL_ROLES = (GUEST, CUSTOMER)

REGISTRY = {}


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    fn: callable
    roles: tuple = ALL_ROLES
    mutates: bool = False  # changes a cart/order/conversation; listed in fallbacks when it succeeded
    label: dict = field(default_factory=dict)  # {"sw": ..., "en": ...} for those fallback lists

    def spec(self):
        return {"type": "function", "function": {
            "name": self.name, "description": self.description, "parameters": self.parameters,
        }}


def register(name, description, properties, required=(), roles=ALL_ROLES, mutates=False, label=None):
    def decorator(fn):
        REGISTRY[name] = Tool(
            name=name, description=description, fn=fn, roles=tuple(roles), mutates=mutates,
            label=label or {},
            parameters={"type": "object", "properties": properties, "required": list(required),
                        "additionalProperties": False},
        )
        return fn
    return decorator


def tools_for(role):
    return [tool for tool in REGISTRY.values() if role in tool.roles]


@dataclass
class ToolContext:
    conversation: object
    user: object = None
    role: str = GUEST
    image_bytes: bytes | None = None
    products: dict = field(default_factory=dict)  # id -> product dict, in order of appearance
    cart: dict | None = None
    order: dict | None = None
    payment: dict | None = None

    @property
    def language(self):
        return self.conversation.language

    def show_products(self, products):
        for product in products:
            self.products[product.pk] = product_card(product)

    def payload(self):
        return {"products": list(self.products.values()), "cart": self.cart,
                "order": self.order, "payment": self.payment}


# --- Argument checking --------------------------------------------------------------------------

_TYPES = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
}


def validate_arguments(tool, args):
    """Return an error message, or None when `args` fits the tool's schema."""
    if not isinstance(args, dict):
        return "Arguments must be a JSON object."
    schema = tool.parameters
    extra = sorted(set(args) - set(schema["properties"]))
    if extra:
        return f"Unknown argument(s): {', '.join(extra)}."
    missing = [name for name in schema["required"] if name not in args or args[name] in (None, "")]
    if missing:
        return f"Missing argument(s): {', '.join(missing)}."
    for name, value in args.items():
        rules = schema["properties"][name]
        if value is None:
            continue
        if not _TYPES[rules["type"]](value):
            return f"Argument {name} must be of type {rules['type']}."
        if "enum" in rules and value not in rules["enum"]:
            return f"Argument {name} must be one of {', '.join(rules['enum'])}."
        if "minimum" in rules and value < rules["minimum"]:
            return f"Argument {name} must be at least {rules['minimum']}."
        if "maximum" in rules and value > rules["maximum"]:
            return f"Argument {name} must be at most {rules['maximum']}."
        if "maxLength" in rules and len(value) > rules["maxLength"]:
            return f"Argument {name} is too long."
    return None


def parse_arguments(raw):
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw or "{}")
    except (TypeError, ValueError):
        return None


def run_tool(ctx, name, raw_arguments):
    """Run one tool call. Returns (ok, result_dict, parsed_arguments)."""
    args = parse_arguments(raw_arguments)
    tool = REGISTRY.get(name)
    if tool is None or ctx.role not in tool.roles:
        return False, {"ok": False, "error": f"There is no tool called {name}."}, args
    if args is None:
        return False, {"ok": False, "error": "Arguments were not valid JSON."}, args
    error = validate_arguments(tool, args)
    if error:
        return False, {"ok": False, "error": error}, args
    args = {key: value for key, value in args.items() if value is not None}
    try:
        with transaction.atomic():
            result = tool.fn(ctx, **args)
    except ShopError as exc:
        return False, {"ok": False, "error": str(exc.detail), **getattr(exc, "extra", {})}, args
    ok = result.get("ok", True)
    return ok, {"ok": ok, **result}, args


# --- Formatting ---------------------------------------------------------------------------------


def money(value):
    if value is None:
        return None
    value = Decimal(value)
    return f"{value:.0f}" if value == value.to_integral_value() else f"{value:.2f}"


def localized(language, english, swahili):
    return swahili if language == "sw" and (swahili or "").strip() else (english or "")


def category_name(product, language):
    if product.category is None:
        return ""
    return localized(language, product.category.name, product.category.name_sw)


def product_card(product):
    """The product shape returned to API clients (server data, never model text)."""
    first = next(iter(product.images.all()), None)
    return {
        "id": product.pk,
        "name": product.name,
        "slug": product.slug,
        "price": f"{product.price:.2f}",
        "compare_at_price": f"{product.compare_at_price:.2f}" if product.compare_at_price else None,
        "in_stock": product.stock > 0,
        "image": first.image.url if first else None,
        "category_name": product.category.name if product.category else None,
    }


def product_brief(product, language):
    """What the model sees about a product in a search result."""
    return {
        "id": product.pk,
        "name": product.name,
        "price_tzs": money(product.price),
        "in_stock": product.stock > 0,
        "category": category_name(product, language),
    }


# --- Product tools ------------------------------------------------------------------------------


@register(
    "search_products",
    "Search the shop's active products by what the shopper describes (any language). Returns "
    "matching products with their current price in TZS.",
    {
        "query": {"type": "string", "maxLength": 200,
                  "description": "What the shopper is looking for, e.g. 'red sneakers' or 'chaja ya simu'."},
        "min_price": {"type": "number", "minimum": 0, "description": "Lowest price in TZS."},
        "max_price": {"type": "number", "minimum": 0, "description": "Highest price in TZS."},
        "category": {"type": "string", "maxLength": 120, "description": "Category name, if the shopper named one."},
        "in_stock_only": {"type": "boolean", "description": "Only products in stock (default true)."},
        "limit": {"type": "integer", "minimum": 1, "maximum": 8, "description": "How many results (default 5)."},
    },
    required=["query"],
)
def search_products(ctx, query, min_price=None, max_price=None, category=None, in_stock_only=True, limit=5):
    products = search.hybrid_products(
        query, min_price=min_price, max_price=max_price, category=category,
        in_stock_only=in_stock_only, limit=limit,
    )
    ctx.show_products(products)
    return {"count": len(products), "products": [product_brief(p, ctx.language) for p in products]}


@register(
    "get_product",
    "Get full details of one product by its id (from a search result).",
    {"product_id": {"type": "integer", "minimum": 1}},
    required=["product_id"],
)
def get_product(ctx, product_id):
    product = (Product.objects.select_related("category").prefetch_related("images")
               .filter(pk=product_id, is_active=True).first())
    if product is None:
        return {"ok": False, "error": "Product not found or no longer available."}
    ctx.show_products([product])
    attributes = product.attributes if isinstance(product.attributes, dict) else {}
    return {
        **product_brief(product, ctx.language),
        "compare_at_price_tzs": money(product.compare_at_price) if product.compare_at_price else None,
        "description": localized(ctx.language, product.description, product.description_sw),
        "sku": product.sku or "",
        "attributes": attributes,
        "image_count": len(product.images.all()),
    }


# --- Cart tools ---------------------------------------------------------------------------------


def conversation_cart(ctx):
    """The cart this chat works on: the customer's own cart, or the guest conversation's cart
    (recreated when it is missing or has expired)."""
    if ctx.user is not None:
        return Cart.objects.get_or_create(user=ctx.user)[0]
    conversation = ctx.conversation
    cart = conversation.cart
    if cart is None or cart.updated_at < timezone.now() - services.GUEST_CART_LIFETIME:
        cart = Cart.objects.create()
        conversation.cart = cart
        conversation.save(update_fields=["cart", "updated_at"])
    return cart


def cart_result(ctx, cart):
    """Show the cart in the reply payload and describe it to the model."""
    totals = services.cart_totals(cart)
    ctx.cart = CartSerializer(totals).data
    return {
        "lines": [
            {"product_id": line["product"].pk, "name": line["product"].name, "quantity": line["quantity"],
             "unit_price_tzs": money(line["unit_price"]), "line_total_tzs": money(line["line_total"])}
            for line in totals["items"]
        ],
        "item_count": totals["item_count"],
        "subtotal_tzs": money(totals["subtotal"]),
    }


@register("view_cart", "Show what is in the shopper's cart, with server prices and the subtotal.", {})
def view_cart(ctx):
    return cart_result(ctx, conversation_cart(ctx))


@register(
    "add_to_cart",
    "Add a product (by id from a search result) to the shopper's cart.",
    {"product_id": {"type": "integer", "minimum": 1},
     "quantity": {"type": "integer", "minimum": 1, "maximum": 20, "description": "How many (default 1)."}},
    required=["product_id"], mutates=True,
    label={"sw": "nimeweka bidhaa kwenye kikapu chako", "en": "added the item to your cart"},
)
def add_to_cart(ctx, product_id, quantity=1):
    cart = conversation_cart(ctx)
    services.add_item(cart, product_id, quantity)
    return cart_result(ctx, cart)


@register(
    "remove_from_cart",
    "Remove a product from the cart. Give quantity to remove only some units; leave it out to "
    "remove the whole line.",
    {"product_id": {"type": "integer", "minimum": 1},
     "quantity": {"type": "integer", "minimum": 1, "maximum": 20}},
    required=["product_id"], mutates=True,
    label={"sw": "nimeondoa bidhaa kwenye kikapu chako", "en": "removed the item from your cart"},
)
def remove_from_cart(ctx, product_id, quantity=None):
    cart = conversation_cart(ctx)
    line = cart.items.filter(product_id=product_id).first()
    if line is None:
        raise services.LineNotFound("This product is not in the cart.")
    if quantity is None or quantity >= line.quantity:
        services.remove_item(cart, product_id)
    else:
        services.set_quantity(cart, product_id, line.quantity - quantity)
    return cart_result(ctx, cart)


# --- Checkout tools -----------------------------------------------------------------------------

DETAIL_FIELDS = ("name", "phone", "email", "region", "district", "street", "notes")
REQUIRED_DETAILS = ("name", "phone", "region", "street")
SERIALIZER_FIELDS = {"contact_name": "name", "contact_phone": "phone"}
CONFIRM_WINDOW = timedelta(minutes=10)


def prefilled(ctx, details):
    """A customer's name, phone, email and default saved address fill any gaps."""
    details = {key: (details.get(key) or "").strip() for key in DETAIL_FIELDS}
    user = ctx.user
    if user is None:
        return details
    details["name"] = details["name"] or user.get_full_name() or user.username
    details["phone"] = details["phone"] or user.phone or ""
    details["email"] = details["email"] or user.email or ""
    address = user.addresses.order_by("-is_default", "pk").first()
    if address and not details["region"] and not details["street"]:
        details.update(region=address.region, district=address.district, street=address.street)
    return details


def check_details(ctx, details, method=Payment.Method.MOBILE_MONEY):
    """Validate like the web checkout. Returns (serializer or None, missing fields, invalid fields)."""
    serializer = CheckoutSerializer(
        data={"contact_name": details["name"], "contact_phone": details["phone"],
              "email": details["email"], "region": details["region"], "district": details["district"],
              "street": details["street"], "notes": details["notes"], "payment_method": method},
        context={"request": SimpleNamespace(user=ctx.user or AnonymousUser())},
    )
    missing = [name for name in REQUIRED_DETAILS if not details[name]]
    if method == Payment.Method.CARD and not details["email"]:
        missing.append("email")
    if serializer.is_valid() and not missing:
        return serializer, [], {}
    invalid = {}
    for field_name, errors in serializer.errors.items():
        name = SERIALIZER_FIELDS.get(field_name, field_name)
        if name not in missing:
            invalid[name] = " ".join(str(e) for e in (errors if isinstance(errors, list) else [errors]))
    return None, missing, invalid


@register(
    "collect_guest_details",
    "Save the shopper's delivery and contact details for checkout. Send only what the shopper "
    "gave; earlier details are kept. Returns which fields are still missing or invalid.",
    {
        "name": {"type": "string", "maxLength": 120},
        "phone": {"type": "string", "maxLength": 20, "description": "Phone, e.g. 0742000331."},
        "region": {"type": "string", "maxLength": 80, "description": "Delivery region, e.g. Dar es Salaam."},
        "street": {"type": "string", "maxLength": 255},
        "district": {"type": "string", "maxLength": 80},
        "notes": {"type": "string", "maxLength": 500},
        "email": {"type": "string", "maxLength": 254, "description": "Needed only to pay by card."},
    },
    mutates=True,
    label={"sw": "nimehifadhi taarifa zako za kufikisha mzigo", "en": "saved your delivery details"},
)
def collect_guest_details(ctx, **given):
    conversation = ctx.conversation
    details = prefilled(ctx, {**(conversation.checkout_details or {}), **given})
    serializer, missing, invalid = check_details(ctx, details)
    if serializer is not None:
        details["phone"] = serializer.validated_data["contact_phone"]
    conversation.checkout_details = details
    conversation.save(update_fields=["checkout_details", "updated_at"])
    return {"ok": not missing and not invalid, "missing": missing, "invalid": invalid, "details": details}


def order_brief(order):
    return {"number": order.number, "status": order.status, "total": f"{order.total:.2f}",
            "currency": settings.SHOP_CURRENCY}


def pay(ctx, order, method, network=None, email=None):
    payment, error = start_payment(order, method=method, network=network, email=email or None)
    order.refresh_from_db()
    ctx.order = order_brief(order)
    if payment is None:
        return {"ok": False, "error": error.message, "order": ctx.order,
                "note": "The order is saved. Calling checkout with confirm=true again retries the payment."}
    ctx.payment = {"method": payment.method, "status": payment.status,
                   "checkout_link": payment.checkout_link, "message": payment_message(payment)}
    return {"order": ctx.order, "payment": ctx.payment}


@register(
    "checkout",
    "Check out the cart. First call with confirm=false to get the order summary (server prices, "
    "delivery fee, total) and show it to the shopper. Only after the shopper says yes, call again "
    "with confirm=true to place the order and start the payment.",
    {
        "confirm": {"type": "boolean"},
        "method": {"type": "string", "enum": [Payment.Method.MOBILE_MONEY, Payment.Method.CARD],
                   "description": "mobile_money (default; a PIN prompt on the phone) or card (a payment link)."},
        "network": {"type": "string", "enum": list(NETWORKS),
                    "description": "Mobile money network, if the shopper said."},
    },
    required=["confirm"], mutates=True,
    label={"sw": "nimeweka oda yako", "en": "placed your order"},
)
def checkout(ctx, confirm, method=Payment.Method.MOBILE_MONEY, network=None):
    conversation = ctx.conversation
    cart = conversation_cart(ctx)
    details = prefilled(ctx, conversation.checkout_details or {})
    last = conversation.last_order
    if not cart.items.exists():
        if confirm and last is not None and last.status == Order.Status.AWAITING_PAYMENT:
            return pay(ctx, last, method, network, details["email"])
        return {"ok": False, "error": "The cart is empty."}

    serializer, missing, invalid = check_details(ctx, details, method)
    if serializer is None:
        return {"ok": False, "missing": missing, "invalid": invalid,
                "error": "Some checkout details are missing or invalid. Ask the shopper, then call "
                         "collect_guest_details."}
    contact, address = serializer.contact, serializer.address
    summary = cart_result(ctx, cart)
    fee = services.delivery_fee_for(address["region"])
    total = services.cart_totals(cart)["subtotal"] + fee
    problem = check_payment_options(Order(total=total, contact_phone=contact["phone"]), method, network,
                                    contact["email"])
    if problem:
        return {"ok": False, "error": problem.message}

    now = timezone.now()
    if not confirm:
        conversation.pending_checkout_at = now
        conversation.save(update_fields=["pending_checkout_at", "updated_at"])
        return {
            **summary, "delivery_fee_tzs": money(fee), "total_tzs": money(total),
            "currency": settings.SHOP_CURRENCY, "payment_method": method,
            "contact": {"name": contact["name"], "phone": contact["phone"]}, "deliver_to": address,
            "next": "Show this summary and ask the shopper to confirm. Then call checkout with confirm=true.",
        }
    if conversation.pending_checkout_at is None or conversation.pending_checkout_at < now - CONFIRM_WINDOW:
        return {"ok": False, "error": "Show the order summary first (checkout with confirm=false) and "
                                      "get the shopper's yes."}
    order = services.place_order(cart, contact, address, user=ctx.user)
    conversation.last_order = order
    conversation.pending_checkout_at = None
    conversation.save(update_fields=["last_order", "pending_checkout_at", "updated_at"])
    ctx.cart = CartSerializer(services.cart_totals(cart)).data
    return pay(ctx, order, method, network, contact["email"])


# --- Orders -------------------------------------------------------------------------------------


@register(
    "order_status",
    "Look up an order's status. Guests must give the order number and the phone used at checkout. "
    "Logged-in customers can leave the number out to get their latest order.",
    {"order_number": {"type": "string", "maxLength": 12},
     "phone": {"type": "string", "maxLength": 20}},
)
def order_status(ctx, order_number=None, phone=None):
    if ctx.user is not None:
        orders = Order.objects.filter(user=ctx.user)
        order = (orders.filter(number=order_number.strip().upper()).first() if order_number
                 else orders.order_by("-placed_at", "-pk").first())
    elif not order_number or not phone:
        return {"ok": False, "error": "I need the order number and the phone number used at checkout."}
    else:
        try:
            order = order_for_phone(order_number, phone)
        except Http404:
            order = None
    if order is None:
        return {"ok": False, "error": "Order not found. Check the order number and the phone used at checkout."}
    ctx.order = order_brief(order)
    event = order.events.order_by("-created_at", "-pk").first()
    return {
        "number": order.number, "status": order.status, "total_tzs": money(order.total),
        "placed_at": order.placed_at.isoformat() if order.placed_at else None,
        "paid_at": order.paid_at.isoformat() if order.paid_at else None,
        "latest_event": {"status": event.status, "note": event.note,
                         "at": event.created_at.isoformat()} if event else None,
    }
