"""Additive hooks for other channels (specs/004-whatsapp-channel/research.md R4)."""

from decimal import Decimal

import pytest

from apps.ai.agent import handle_message
from apps.ai.models import ChatMessage, Conversation
from apps.ai.testing import tool_call
from apps.ai.tools import GUEST, ToolContext, conversation_cart, run_tool
from apps.orders import services
from apps.orders.models import Cart, Order

pytestmark = pytest.mark.django_db

PHONE = "+255742000331"


def test_record_only_stores_the_message_with_meta_and_calls_no_model(conversation, chat_model):
    reply = handle_message(conversation, text="habari", record_only=True,
                           meta={"whatsapp": {"type": "text", "wa_message_id": "wamid.1"}})

    assert chat_model.requests == []
    assert reply.message is None
    assert reply.incoming.role == ChatMessage.Role.USER
    assert reply.incoming.payload == {"whatsapp": {"type": "text", "wa_message_id": "wamid.1"}}
    assert list(conversation.messages.values_list("role", flat=True)) == ["user"]


def test_meta_is_stored_on_a_normal_turn(conversation, chat_model):
    chat_model.add("Karibu")
    reply = handle_message(conversation, text="habari", meta={"whatsapp": {"type": "text"}})
    assert reply.incoming.payload == {"whatsapp": {"type": "text"}}
    assert reply.text == "Karibu"


def test_verified_phone_prefills_checkout_phone(conversation, product, region):
    ctx = ToolContext(conversation=conversation, role=GUEST, verified_phone=PHONE)
    ok, result, _ = run_tool(ctx, "collect_guest_details",
                             {"name": "Asha", "region": "Dar es Salaam", "street": "Mtaa 1"})
    assert ok, result
    assert result["details"]["phone"] == PHONE

    services.add_item(conversation_cart(ctx), product.pk, 1)
    ok, result, _ = run_tool(ctx, "checkout", {"confirm": False})
    assert ok, result
    assert result["contact"]["phone"] == PHONE


def test_shopper_given_phone_wins_over_verified_phone(conversation):
    ctx = ToolContext(conversation=conversation, role=GUEST, verified_phone=PHONE)
    _, result, _ = run_tool(ctx, "collect_guest_details", {"phone": "0712000009"})
    assert result["details"]["phone"] == "0712000009"


def test_order_status_with_phone_orders_and_no_number(conversation, make_order):
    old = make_order(phone="+255799000001")
    newest = make_order(phone="+255799000002")
    make_order()  # not in phone_orders
    ctx = ToolContext(conversation=conversation, role=GUEST,
                      phone_orders=Order.objects.filter(pk__in=[old.pk, newest.pk]))
    ok, result, _ = run_tool(ctx, "order_status", {})
    assert ok, result
    assert result["number"] == newest.number


def test_order_status_by_number_inside_phone_orders(conversation, make_order):
    mine = make_order(phone="+255799000001")
    make_order()
    ctx = ToolContext(conversation=conversation, role=GUEST, phone_orders=Order.objects.filter(pk=mine.pk))
    ok, result, _ = run_tool(ctx, "order_status", {"order_number": mine.number})
    assert ok and result["number"] == mine.number


def test_order_outside_phone_orders_still_needs_the_phone(conversation, make_order):
    mine = make_order(phone="+255799000001")
    other = make_order(phone="+255712345678")
    ctx = ToolContext(conversation=conversation, role=GUEST, phone_orders=Order.objects.filter(pk=mine.pk))

    ok, result, _ = run_tool(ctx, "order_status", {"order_number": other.number})
    assert not ok

    ok, result, _ = run_tool(ctx, "order_status", {"order_number": other.number, "phone": "0712345678"})
    assert ok and result["number"] == other.number


def test_order_status_without_phone_orders_is_unchanged(conversation):
    ctx = ToolContext(conversation=conversation, role=GUEST)
    ok, result, _ = run_tool(ctx, "order_status", {})
    assert not ok and "order number" in result["error"]


def test_checkout_summary_is_set_on_the_summary_path(conversation, product, region):
    ctx = ToolContext(conversation=conversation, role=GUEST, verified_phone=PHONE)
    services.add_item(conversation_cart(ctx), product.pk, 2)
    run_tool(ctx, "collect_guest_details", {"name": "Asha", "region": "Dar es Salaam", "street": "Mtaa 1"})
    run_tool(ctx, "checkout", {"confirm": False})

    summary = ctx.checkout_summary
    assert summary["total"] == Decimal("93000")
    assert summary["fee"] == Decimal("3000")
    assert summary["subtotal"] == Decimal("90000")
    assert summary["method"] == "mobile_money"
    assert summary["network"] == ""
    assert summary["lines"] == [(product.pk, 2, Decimal("45000.00"))]
    assert summary["details"]["phone"] == PHONE


def test_unseen_confirm_also_sets_the_summary(conversation, product, region):
    ctx = ToolContext(conversation=conversation, role=GUEST, verified_phone=PHONE)
    services.add_item(conversation_cart(ctx), product.pk, 1)
    run_tool(ctx, "collect_guest_details", {"name": "Asha", "region": "Dar es Salaam", "street": "Mtaa 1"})
    ok, _, _ = run_tool(ctx, "checkout", {"confirm": True})
    assert not ok
    assert ctx.checkout_summary["total"] == Decimal("48000")


def test_agent_reply_carries_summary_and_incoming(conversation, chat_model, product, region):
    services.add_item(conversation.cart, product.pk, 1)
    chat_model.add(
        [tool_call("collect_guest_details", name="Asha", region="Dar es Salaam", street="Mtaa 1")],
        [tool_call("checkout", confirm=False)],
        "Jumla 48,000. Thibitisha?",
    )
    reply = handle_message(conversation, text="nataka kulipa", verified_phone=PHONE)
    assert reply.summary["total"] == Decimal("48000")
    assert reply.incoming.text == "nataka kulipa"
    assert "summary" not in reply.payload


def test_plain_reply_has_no_summary(conversation, chat_model):
    reply = handle_message(conversation, text="habari")
    assert reply.summary is None
    assert reply.incoming.text == "habari"


def test_chat_api_response_keys_unchanged(api_client, chat_model):
    chat_model.add("Karibu!")
    body = api_client.post("/api/ai/chat/", {"message": "habari"}, format="json").json()
    assert set(body) == {"conversation_token", "cart_token", "reply", "language", "state", "products",
                         "cart", "order", "payment", "error"}
    assert Conversation.objects.get().cart == Cart.objects.get()
