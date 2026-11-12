"""US2: ordering and paying from WhatsApp (T029, research R6/R8)."""

import uuid
from datetime import timedelta

import pytest

from apps.ai.models import ChatMessage, Conversation
from apps.ai.testing import tool_call
from apps.orders import services
from apps.orders.models import Cart, Order
from apps.whatsapp import testing as wa
from apps.whatsapp.models import WhatsAppCheckoutPrompt as Prompt, WhatsAppContact, WhatsAppOrder

pytestmark = pytest.mark.django_db

ASHA = "255742000331"
DETAILS = {"name": "Asha Mussa", "region": "Dar es Salaam", "street": "Mtaa wa Uhuru 12"}


@pytest.fixture
def shop(shoe_catalog, region, stakaba):
    return shoe_catalog


def buttons(graph):
    return [body["interactive"] for body in graph.sent if body.get("type") == "interactive"]


def prompt_ids(graph):
    ids = [b["action"]["buttons"][0]["reply"]["id"] for b in buttons(graph)]
    return [i.split(":", 1)[1] for i in ids]


def to_summary(deliver_inbound, chat_model, shop, wa_id=ASHA, quantity=1):
    """Three messages: add a product, give the details, ask for the summary."""
    chat_model.add([tool_call("add_to_cart", product_id=shop.red.pk, quantity=quantity)],
                   "Nimeongeza Red Sneakers kwenye kikapu.")
    deliver_inbound(wa.text_message("nataka red sneakers", wa_id=wa_id))
    chat_model.add([tool_call("collect_guest_details", **DETAILS)], "Asante, nimehifadhi.")
    deliver_inbound(wa.text_message("Asha Mussa, Dar es Salaam, Mtaa wa Uhuru 12", wa_id=wa_id))
    chat_model.add([tool_call("checkout", confirm=False)], "Muhtasari: Red Sneakers x1. Jumla 48,000 TZS.")
    deliver_inbound(wa.text_message("nataka kulipa", wa_id=wa_id))


def tap(deliver_inbound, kind, prompt_id, wa_id=ASHA):
    return deliver_inbound(wa.button_reply(f"{kind}:{prompt_id}", wa_id=wa_id))


def test_whatsapp_number_is_the_contact_phone(deliver_inbound, chat_model, shop):
    chat_model.add([tool_call("collect_guest_details", **DETAILS)], "Asante.")
    deliver_inbound(wa.text_message("Asha Mussa, Dar es Salaam, Mtaa wa Uhuru 12"))
    conversation = WhatsAppContact.objects.get().conversation
    assert conversation.checkout_details["phone"] == "+255742000331"
    call = conversation.messages.get(role="assistant").tool_calls[0]
    assert call["ok"] is True  # nothing missing: name, region and street were enough


def test_summary_is_followed_by_buttons_with_the_db_total(deliver_inbound, chat_model, graph, shop):
    to_summary(deliver_inbound, chat_model, shop, quantity=2)

    last = graph.sent[-1]
    assert last["type"] == "interactive"
    body = last["interactive"]["body"]["text"]
    assert body == "Jumla: 93,000 TZS (pamoja na usafirishaji 3,000). Thibitisha oda?"
    ids = [b["reply"]["id"] for b in last["interactive"]["action"]["buttons"]]
    prompt = Prompt.objects.get()
    assert ids == [f"confirm:{prompt.pk}", f"change:{prompt.pk}"]
    titles = [b["reply"]["title"] for b in last["interactive"]["action"]["buttons"]]
    assert titles == ["Thibitisha", "Badilisha"]
    assert graph.sent[-2]["type"] == "text"  # the assistant's own summary text comes first


def test_confirm_tap_places_one_order_without_the_model(deliver_inbound, chat_model, graph, shop, stakaba):
    to_summary(deliver_inbound, chat_model, shop)
    requests_before = len(chat_model.requests)
    prompt_id = prompt_ids(graph)[-1]

    tap(deliver_inbound, "confirm", prompt_id)

    assert len(chat_model.requests) == requests_before  # no model call
    order = Order.objects.get()
    assert order.total == 48000
    assert WhatsAppOrder.objects.get(order=order).contact == WhatsAppContact.objects.get()
    assert Prompt.objects.get().order == order
    assert graph.texts[-1] == (
        f"Oda {order.number}: jumla 48,000 TZS. Angalia simu yako (+255742000331) uweke PIN kukamilisha malipo."
    )
    conversation = WhatsAppContact.objects.get().conversation
    rows = list(conversation.messages.order_by("created_at", "id"))[-2:]
    assert rows[0].role == "user" and rows[0].payload["whatsapp"]["button"] == "confirm"
    assert rows[1].role == "assistant" and rows[1].tool_calls[0]["name"] == "checkout"

    # a second tap on the same button: still one order, the payment text again
    tap(deliver_inbound, "confirm", prompt_id)
    assert Order.objects.count() == 1
    assert graph.texts[-1].startswith(f"Oda {order.number}: jumla 48,000 TZS.")
    assert len(stakaba.requests_to("/payments/collection")) == 1


def test_typed_confirm_sends_the_server_payment_text(deliver_inbound, chat_model, graph, shop):
    to_summary(deliver_inbound, chat_model, shop)
    chat_model.add([tool_call("checkout", confirm=True)], "Oda imewekwa!")
    deliver_inbound(wa.text_message("ndiyo"))

    order = Order.objects.get()
    assert WhatsAppOrder.objects.filter(order=order).exists()
    assert graph.texts[-2] == "Oda imewekwa!"
    assert graph.texts[-1].startswith(f"Oda {order.number}: jumla 48,000 TZS. Angalia simu yako")


def test_card_payment_text_has_the_checkout_link(deliver_inbound, chat_model, graph, shop):
    to_summary(deliver_inbound, chat_model, shop)
    chat_model.add([tool_call("collect_guest_details", email="asha@example.com"),
                    tool_call("checkout", confirm=False, method="card")], "Muhtasari kwa kadi.")
    deliver_inbound(wa.text_message("nitalipa kwa kadi, asha@example.com"))
    tap(deliver_inbound, "confirm", prompt_ids(graph)[-1])

    order = Order.objects.get()
    assert graph.texts[-1] == f"Oda {order.number}: jumla 48,000 TZS. Lipa hapa: https://pay.test/{order.payments.get().reference}"


def test_confirm_after_a_cart_change_is_refused_with_a_fresh_summary(deliver_inbound, chat_model, graph, shop):
    to_summary(deliver_inbound, chat_model, shop)
    old = prompt_ids(graph)[-1]
    cart = WhatsAppContact.objects.get().conversation.cart
    services.add_item(cart, shop.charger.pk, 1)

    tap(deliver_inbound, "confirm", old)

    assert not Order.objects.exists()
    assert "Kikapu kimebadilika" in graph.texts[-1]
    new = prompt_ids(graph)[-1]
    assert new != old
    assert buttons(graph)[-1]["body"]["text"].startswith("Jumla: 63,000 TZS")
    tap(deliver_inbound, "confirm", new)
    assert Order.objects.get().total == 63000


def test_confirm_on_an_older_prompt_is_refused(deliver_inbound, chat_model, graph, shop):
    to_summary(deliver_inbound, chat_model, shop)
    old = prompt_ids(graph)[-1]
    chat_model.add([tool_call("checkout", confirm=False)], "Muhtasari tena.")
    deliver_inbound(wa.text_message("nionyeshe muhtasari tena"))

    tap(deliver_inbound, "confirm", old)
    assert not Order.objects.exists()
    assert prompt_ids(graph)[-1] not in (old,)


def test_confirm_after_ten_minutes_is_refused(deliver_inbound, chat_model, graph, shop):
    to_summary(deliver_inbound, chat_model, shop)
    prompt = Prompt.objects.get()
    Prompt.objects.filter(pk=prompt.pk).update(created_at=prompt.created_at - timedelta(minutes=11))

    tap(deliver_inbound, "confirm", prompt.pk)
    assert not Order.objects.exists()
    assert Prompt.objects.count() == 2


def test_unknown_or_foreign_prompt_is_expired(deliver_inbound, chat_model, graph, shop):
    to_summary(deliver_inbound, chat_model, shop, wa_id="255742000999")
    foreign = prompt_ids(graph)[-1]

    tap(deliver_inbound, "confirm", foreign)  # from another number
    assert graph.texts[-1] == "Kitufe hicho kimeisha muda."
    tap(deliver_inbound, "confirm", uuid.uuid4())
    assert graph.texts[-1] == "Kitufe hicho kimeisha muda."
    deliver_inbound(wa.button_reply("garbage"))
    assert graph.texts[-1] == "Kitufe hicho kimeisha muda."
    assert not Order.objects.exists()


def test_change_tap_asks_the_assistant(deliver_inbound, chat_model, graph, shop):
    to_summary(deliver_inbound, chat_model, shop)
    chat_model.add("Ungependa kubadilisha nini?")
    tap(deliver_inbound, "change", prompt_ids(graph)[-1])

    assert chat_model.last_messages[-1]["content"] == "Nataka kubadilisha kitu"
    assert graph.texts[-1] == "Ungependa kubadilisha nini?"
    assert not Order.objects.exists()


# --- Order lookups (US2-4/5/6) --------------------------------------------------------------------


@pytest.fixture
def placed(deliver_inbound, chat_model, graph, shop):
    to_summary(deliver_inbound, chat_model, shop)
    tap(deliver_inbound, "confirm", prompt_ids(graph)[-1])
    return Order.objects.get()


def last_tool_result(chat_model):
    return chat_model.requests[-1]["messages"][-1]["content"]


def test_own_order_needs_no_number_or_phone(deliver_inbound, chat_model, placed):
    chat_model.add([tool_call("order_status")], "Oda yako inasubiri malipo.")
    deliver_inbound(wa.text_message("oda yangu iko wapi?"))
    assert placed.number in last_tool_result(chat_model)


def test_another_numbers_order_needs_number_and_phone(deliver_inbound, chat_model, placed):
    chat_model.add([tool_call("order_status", order_number=placed.number)], "Nipe namba ya simu.")
    deliver_inbound(wa.text_message(f"oda {placed.number}?", wa_id="255742000999"))
    result = last_tool_result(chat_model)
    assert '"ok": false' in result and "awaiting_payment" not in result


def test_registered_but_unlinked_phone_sees_only_whatsapp_orders(deliver_inbound, chat_model, customer,
                                                                 make_order, placed):
    web_order = make_order(user=customer, phone="+255742000331")
    chat_model.add([tool_call("order_status")], "Hii hapa.")
    deliver_inbound(wa.text_message("oda yangu?"))
    result = last_tool_result(chat_model)
    assert placed.number in result and web_order.number not in result


def test_two_numbers_have_separate_conversations_and_carts(deliver_inbound, chat_model, shop):
    chat_model.add([tool_call("add_to_cart", product_id=shop.red.pk)], "Sawa.")
    deliver_inbound(wa.text_message("red sneakers", wa_id=ASHA))
    chat_model.add([tool_call("checkout", confirm=False)], "Kikapu kiko tupu.")
    deliver_inbound(wa.text_message("nataka kulipa", wa_id="255742000999"))

    a, b = (WhatsAppContact.objects.get(wa_id=w) for w in (ASHA, "255742000999"))
    assert a.conversation != b.conversation and a.conversation.cart != b.conversation.cart
    assert b.conversation.cart.items.count() == 0
    assert '"The cart is empty."' in last_tool_result(chat_model)


def test_question_to_payment_in_six_messages(deliver_inbound, chat_model, graph, shop):
    """SC-004: question, add, details, summary, confirm tap -> payment text (5 inbound messages)."""
    chat_model.add([tool_call("search_products", query="raba nyekundu")], "Tuna Red Sneakers kwa 45,000 TZS.")
    deliver_inbound(wa.text_message("mna raba nyekundu?"))
    to_summary(deliver_inbound, chat_model, shop)
    tap(deliver_inbound, "confirm", prompt_ids(graph)[-1])

    contact = WhatsAppContact.objects.get()
    assert contact.conversation.messages.filter(role=ChatMessage.Role.USER).count() <= 6
    assert graph.texts[-1].startswith(f"Oda {Order.objects.get().number}")
    assert Conversation.objects.count() == 1 and Cart.objects.filter(items__isnull=False).count() == 0
