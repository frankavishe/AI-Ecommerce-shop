from datetime import timedelta

import pytest
from django.utils import timezone

from apps.ai.models import Conversation
from apps.ai.tools import CUSTOMER, GUEST, ToolContext, conversation_cart, run_tool
from apps.orders import services
from apps.orders.models import Cart
from apps.orders.serializers import CartSerializer


@pytest.fixture
def guest_ctx(conversation):
    return ToolContext(conversation=conversation, role=GUEST)


@pytest.fixture
def customer_ctx(db, customer):
    return ToolContext(conversation=Conversation.objects.create(user=customer), user=customer, role=CUSTOMER)


def test_guest_add_to_cart_uses_the_conversation_cart(guest_ctx, product, api_client):
    ok, result, _ = run_tool(guest_ctx, "add_to_cart", {"product_id": product.pk, "quantity": 2})

    assert ok and result["item_count"] == 2
    cart = guest_ctx.conversation.cart
    assert cart.items.get().quantity == 2
    response = api_client.get("/api/cart/", HTTP_X_CART_TOKEN=cart.token)
    assert response.json()["item_count"] == 2
    assert guest_ctx.cart == response.json()  # the reply payload has the shop CartSerializer shape


def test_customer_add_to_cart_uses_the_user_cart(customer_ctx, customer, product):
    ok, _, _ = run_tool(customer_ctx, "add_to_cart", {"product_id": product.pk})

    assert ok
    assert Cart.objects.get(user=customer).items.get().product == product
    assert customer_ctx.conversation.cart is None


def test_quantity_is_limited_to_twenty(guest_ctx, product):
    ok, result, _ = run_tool(guest_ctx, "add_to_cart", {"product_id": product.pk, "quantity": 21})
    assert not ok and "at most 20" in result["error"]


def test_over_stock_reports_available_and_leaves_the_cart(guest_ctx, make_product):
    item = make_product(stock=3)
    run_tool(guest_ctx, "add_to_cart", {"product_id": item.pk, "quantity": 2})

    ok, result, _ = run_tool(guest_ctx, "add_to_cart", {"product_id": item.pk, "quantity": 2})

    assert not ok
    assert result["available"] == 3
    assert guest_ctx.conversation.cart.items.get().quantity == 2


def test_inactive_product_is_refused(guest_ctx, make_product):
    item = make_product(is_active=False)
    ok, result, _ = run_tool(guest_ctx, "add_to_cart", {"product_id": item.pk})
    assert not ok and "no longer available" in result["error"]
    assert not guest_ctx.conversation.cart.items.exists()


def test_remove_part_of_a_line_then_all_of_it(guest_ctx, product):
    run_tool(guest_ctx, "add_to_cart", {"product_id": product.pk, "quantity": 3})

    ok, result, _ = run_tool(guest_ctx, "remove_from_cart", {"product_id": product.pk, "quantity": 1})
    assert ok and result["item_count"] == 2

    ok, result, _ = run_tool(guest_ctx, "remove_from_cart", {"product_id": product.pk})
    assert ok and result["item_count"] == 0
    assert not guest_ctx.conversation.cart.items.exists()


def test_removing_more_than_the_line_removes_it(guest_ctx, product):
    run_tool(guest_ctx, "add_to_cart", {"product_id": product.pk, "quantity": 2})
    ok, result, _ = run_tool(guest_ctx, "remove_from_cart", {"product_id": product.pk, "quantity": 5})
    assert ok and result["item_count"] == 0


def test_remove_a_product_not_in_the_cart(guest_ctx, product):
    ok, result, _ = run_tool(guest_ctx, "remove_from_cart", {"product_id": product.pk, "quantity": 1})
    assert not ok and "not in the cart" in result["error"]


def test_view_cart_totals_match_cart_totals(guest_ctx, make_product):
    a, b = make_product(price=45000), make_product(price=15000)
    cart = conversation_cart(guest_ctx)
    services.add_item(cart, a.pk, 2)
    services.add_item(cart, b.pk, 1)

    ok, result, _ = run_tool(guest_ctx, "view_cart", {})

    totals = services.cart_totals(cart)
    assert ok
    assert result["subtotal_tzs"] == "105000"
    assert result["item_count"] == totals["item_count"] == 3
    assert [line["quantity"] for line in result["lines"]] == [2, 1]
    assert guest_ctx.cart == CartSerializer(totals).data
    assert guest_ctx.payload()["cart"]["subtotal"] == "105000.00"


def test_missing_or_expired_guest_cart_is_recreated(conversation):
    ctx = ToolContext(conversation=conversation, role=GUEST)
    old = conversation.cart
    Cart.objects.filter(pk=old.pk).update(updated_at=timezone.now() - timedelta(days=31))
    conversation.cart.refresh_from_db()

    fresh = conversation_cart(ctx)
    assert fresh.pk != old.pk
    assert Conversation.objects.get(pk=conversation.pk).cart_id == fresh.pk

    conversation.cart = None
    conversation.save()
    assert conversation_cart(ctx).pk not in (None, old.pk, fresh.pk)
