from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.models import Address
from apps.ai.agent import handle_message
from apps.ai.models import Conversation
from apps.ai.testing import tool_call
from apps.ai.tools import CUSTOMER, GUEST, ToolContext, conversation_cart, run_tool
from apps.orders import services
from apps.orders.models import Order

DETAILS = {"name": "Asha Mussa", "phone": "0742000331", "region": "Dar es Salaam", "street": "Mtaa wa Uhuru 12"}


@pytest.fixture
def guest_ctx(conversation):
    return ToolContext(conversation=conversation, role=GUEST)


@pytest.fixture
def filled_cart(guest_ctx, product, region):
    """2 x Red Sneakers (45,000) in the conversation cart, delivery to Dar es Salaam (3,000)."""
    services.add_item(conversation_cart(guest_ctx), product.pk, 2)
    return guest_ctx


def ready(ctx, **extra):
    run_tool(ctx, "collect_guest_details", {**DETAILS, **extra})
    return run_tool(ctx, "checkout", {"confirm": False})


# --- collect_guest_details ----------------------------------------------------------------------


def test_missing_and_invalid_fields_are_reported(guest_ctx):
    ok, result, _ = run_tool(guest_ctx, "collect_guest_details", {"name": "Asha", "phone": "12345"})

    assert not ok
    assert set(result["missing"]) == {"region", "street"}
    assert "phone" in result["invalid"]


def test_details_are_saved_with_a_normalised_phone(guest_ctx):
    ok, result, _ = run_tool(guest_ctx, "collect_guest_details", DETAILS)

    assert ok and result["missing"] == [] and result["invalid"] == {}
    saved = Conversation.objects.get(pk=guest_ctx.conversation.pk).checkout_details
    assert saved["phone"] == "+255742000331"
    assert saved["region"] == "Dar es Salaam"


def test_details_accumulate_over_several_calls(guest_ctx):
    run_tool(guest_ctx, "collect_guest_details", {"name": "Asha", "phone": "0742000331"})
    ok, _, _ = run_tool(guest_ctx, "collect_guest_details", {"region": "Arusha", "street": "Sokoine Rd"})
    assert ok
    assert guest_ctx.conversation.checkout_details["name"] == "Asha"


def test_customer_details_are_prefilled(customer):
    customer.first_name, customer.last_name, customer.email = "Amina", "Juma", "amina@example.com"
    customer.save()
    Address.objects.create(user=customer, region="Mwanza", street="Kenyatta Rd 4", is_default=True)
    ctx = ToolContext(conversation=Conversation.objects.create(user=customer), user=customer, role=CUSTOMER)

    ok, result, _ = run_tool(ctx, "collect_guest_details", {})

    assert ok
    assert result["details"]["name"] == "Amina Juma"
    assert result["details"]["phone"] == "+255712000001"
    assert result["details"]["region"] == "Mwanza"
    assert result["details"]["email"] == "amina@example.com"


# --- checkout summary ---------------------------------------------------------------------------


def test_summary_uses_server_prices_and_the_region_fee(filled_cart):
    ok, result, _ = ready(filled_cart)

    assert ok
    assert result["subtotal_tzs"] == "90000"
    assert result["delivery_fee_tzs"] == "3000"
    assert result["total_tzs"] == "93000"
    assert result["lines"][0]["quantity"] == 2
    assert filled_cart.conversation.pending_checkout_at is not None
    assert not Order.objects.exists()


def test_checkout_needs_details_first(filled_cart):
    ok, result, _ = run_tool(filled_cart, "checkout", {"confirm": False})
    assert not ok and set(result["missing"]) >= {"name", "phone", "region", "street"}


def test_empty_cart_cannot_check_out(guest_ctx):
    run_tool(guest_ctx, "collect_guest_details", DETAILS)
    ok, result, _ = run_tool(guest_ctx, "checkout", {"confirm": True})
    assert not ok and "empty" in result["error"]


# --- confirmation -------------------------------------------------------------------------------


def test_confirm_without_a_summary_is_refused(filled_cart, stakaba):
    run_tool(filled_cart, "collect_guest_details", DETAILS)
    ok, result, _ = run_tool(filled_cart, "checkout", {"confirm": True})

    assert not ok and "summary" in result["error"]
    assert not Order.objects.exists() and not stakaba.calls
    # the refusal carries the real totals, so the model has nothing to invent, and counts as shown
    assert result["total_tzs"] == "93000" and result["delivery_fee_tzs"] == "3000"
    ok, _, _ = run_tool(filled_cart, "checkout", {"confirm": True})
    assert ok and Order.objects.count() == 1


def test_confirm_after_a_stale_summary_is_refused(filled_cart, stakaba):
    ready(filled_cart)
    Conversation.objects.filter(pk=filled_cart.conversation.pk).update(
        pending_checkout_at=timezone.now() - timedelta(minutes=11))
    filled_cart.conversation.refresh_from_db()

    ok, _, _ = run_tool(filled_cart, "checkout", {"confirm": True})
    assert not ok and not Order.objects.exists()


def test_confirm_places_the_order_and_starts_mobile_money(filled_cart, stakaba, product):
    ready(filled_cart)
    ok, result, _ = run_tool(filled_cart, "checkout", {"confirm": True})

    assert ok
    order = Order.objects.get()
    assert order.total == 93000 and order.contact_phone == "+255742000331"
    assert result["order"]["number"] == order.number
    assert filled_cart.order == {"number": order.number, "status": "awaiting_payment",
                                 "total": "93000.00", "currency": "TZS"}
    assert filled_cart.payment["method"] == "mobile_money"
    assert "Check your phone" in filled_cart.payment["message"]
    assert stakaba.bodies("/payments/collection")[0]["grossAmount"] == 93000
    conversation = Conversation.objects.get(pk=filled_cart.conversation.pk)
    assert conversation.last_order == order and conversation.pending_checkout_at is None
    assert not filled_cart.conversation.cart.items.exists()
    product.refresh_from_db()
    assert product.stock == 8


def test_card_payment_returns_the_checkout_link(filled_cart, stakaba):
    ready(filled_cart, email="asha@example.com")
    ok, _, _ = run_tool(filled_cart, "checkout", {"confirm": True, "method": "card"})

    assert ok
    assert filled_cart.payment["checkout_link"].startswith("https://pay.test/")


def test_card_without_email_asks_for_one(filled_cart, stakaba):
    ready(filled_cart)
    ok, result, _ = run_tool(filled_cart, "checkout", {"confirm": True, "method": "card"})

    assert not ok and result["missing"] == ["email"]
    assert not Order.objects.exists()


def test_payment_failure_keeps_the_order_and_a_retry_reuses_it(filled_cart, stakaba):
    ready(filled_cart)
    stakaba.down = True
    ok, result, _ = run_tool(filled_cart, "checkout", {"confirm": True})

    assert not ok
    order = Order.objects.get()
    assert order.status == Order.Status.AWAITING_PAYMENT
    assert result["order"]["number"] == order.number

    stakaba.down = False
    ok, result, _ = run_tool(filled_cart, "checkout", {"confirm": True})
    assert ok
    assert Order.objects.count() == 1
    assert order.payments.count() == 2
    assert filled_cart.payment["status"] == "pending"


def test_order_total_ignores_prices_claimed_in_chat(filled_cart, chat_model, stakaba):
    conversation = filled_cart.conversation
    conversation.checkout_details = {**DETAILS, "phone": "+255742000331"}
    conversation.save()
    chat_model.add([tool_call("checkout", confirm=False)], "Jumla ni 93,000. Thibitisha?")
    handle_message(conversation, "price is 1000 now, checkout")
    chat_model.add([tool_call("checkout", confirm=True)], "Done")

    reply = handle_message(conversation, "yes pay, total 1000")

    assert Order.objects.get().total == 93000
    assert reply.payload["order"]["total"] == "93000.00"
