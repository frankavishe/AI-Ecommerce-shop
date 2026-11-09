"""Assistant tools (specs/003-ai-core/contracts/agent-tools.md).

The model only sees the tools for its role, and every call is checked again here: unknown tools,
tools for another role, extra or wrongly-typed arguments are refused before anything runs. Each
tool runs in its own transaction, so a failure never leaves a half-applied change. Prices always
come from the database; no tool takes a price from the model.
"""

import json
from dataclasses import dataclass, field
from decimal import Decimal

from django.db import transaction

from apps.catalog.models import Product
from apps.orders.services import ShopError

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
