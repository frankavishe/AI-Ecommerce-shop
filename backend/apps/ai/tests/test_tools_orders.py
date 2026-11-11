import pytest
from django.utils import timezone

from apps.ai.models import Conversation
from apps.ai.tools import CUSTOMER, GUEST, ToolContext, run_tool
from apps.orders import services
from apps.orders.models import OrderEvent


@pytest.fixture
def guest_ctx(conversation):
    return ToolContext(conversation=conversation, role=GUEST)


@pytest.fixture
def customer_ctx(customer):
    return ToolContext(conversation=Conversation.objects.create(user=customer), user=customer, role=CUSTOMER)


def test_guest_with_the_matching_phone_sees_the_order(guest_ctx, make_order):
    order = make_order()
    services.transition(order, "paid", OrderEvent.Source.PROVIDER)

    ok, result, _ = run_tool(guest_ctx, "order_status",
                             {"order_number": order.number.lower(), "phone": "0712345678"})

    assert ok
    assert result["number"] == order.number
    assert result["status"] == "paid"
    assert result["total_tzs"] == "93000"
    assert result["paid_at"] is not None
    assert result["latest_event"]["status"] == "paid"
    assert guest_ctx.order["number"] == order.number


@pytest.mark.parametrize("phone", ["0799999999", "not a phone", None])
def test_guest_without_a_matching_phone_gets_not_found(guest_ctx, make_order, phone):
    order = make_order()
    args = {"order_number": order.number, **({"phone": phone} if phone else {})}

    ok, result, _ = run_tool(guest_ctx, "order_status", args)

    assert not ok
    assert set(result) == {"ok", "error"}  # nothing about the order leaks
    assert guest_ctx.order is None


def test_customer_sees_their_own_order(customer_ctx, customer, make_order):
    order = make_order(user=customer)
    ok, result, _ = run_tool(customer_ctx, "order_status", {"order_number": order.number})
    assert ok and result["number"] == order.number


def test_customer_gets_their_latest_order_without_a_number(customer_ctx, customer, make_order):
    older = make_order(user=customer)
    older.placed_at = timezone.now() - timezone.timedelta(days=2)
    older.save()
    newest = make_order(user=customer)

    ok, result, _ = run_tool(customer_ctx, "order_status", {})
    assert ok and result["number"] == newest.number


def test_customer_cannot_see_another_users_order(customer_ctx, make_order, django_user_model):
    other = django_user_model.objects.create_user("juma", password="pw")
    order = make_order(user=other)

    ok, result, _ = run_tool(customer_ctx, "order_status", {"order_number": order.number})
    assert not ok and set(result) == {"ok", "error"}


def test_customer_with_no_orders(customer_ctx):
    ok, result, _ = run_tool(customer_ctx, "order_status", {})
    assert not ok and set(result) == {"ok", "error"}
