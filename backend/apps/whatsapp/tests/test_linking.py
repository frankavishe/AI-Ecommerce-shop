"""US2: linking a WhatsApp number to a web account (T030, research R13, contracts/link-api.md)."""

import hashlib
from datetime import timedelta

import pytest
from django.core.cache import cache
from django.utils import timezone

from apps.accounts.models import Address, User
from apps.ai.models import Conversation
from apps.ai.testing import tool_call
from apps.orders import services
from apps.orders.models import Cart
from apps.whatsapp import linking
from apps.whatsapp import testing as wa
from apps.whatsapp.models import WhatsAppContact, WhatsAppLinkCode

pytestmark = pytest.mark.django_db

URL, CODE_URL = "/api/whatsapp/link/", "/api/whatsapp/link/code/"


@pytest.fixture(autouse=True)
def _fresh_throttles():
    cache.clear()
    yield
    cache.clear()


def new_code(user):
    return linking.issue_code(user)["code"]


# --- API ------------------------------------------------------------------------------------------


def test_get_when_not_linked(auth_client, customer):
    response = auth_client(customer).get(URL)
    assert response.status_code == 200
    assert response.json() == {"linked": False, "number": None, "linked_at": None,
                               "business_number": "+255700000000"}


def test_get_when_linked_masks_the_number(auth_client, customer, contact_factory):
    contact_factory(user=customer, linked_at=timezone.now())
    body = auth_client(customer).get(URL).json()
    assert body["linked"] is True and body["number"] == "+255 742 *** 331" and body["linked_at"]


def test_post_creates_a_hashed_code(auth_client, customer):
    response = auth_client(customer).post(CODE_URL)
    assert response.status_code == 201
    body = response.json()
    code = body["code"]
    assert code.startswith("LINK-") and len(code) == 11
    assert set(code[5:]) <= set("ABCDEFGHJKLMNPQRSTUVWXYZ23456789")
    assert body["wa_link"] == f"https://wa.me/255700000000?text={code}"
    row = WhatsAppLinkCode.objects.get()
    assert row.code_hash == hashlib.sha256(code[5:].encode()).hexdigest()
    assert code[5:] not in row.code_hash
    assert timedelta(minutes=9) < row.expires_at - timezone.now() <= timedelta(minutes=10)


def test_a_new_code_voids_the_old_one(auth_client, customer, contact_factory, deliver_inbound):
    client = auth_client(customer)
    old = client.post(CODE_URL).json()["code"]
    client.post(CODE_URL)
    contact_factory()
    deliver_inbound(wa.text_message(old))
    assert WhatsAppContact.objects.get().user is None


def test_code_requests_are_throttled(auth_client, customer):
    client = auth_client(customer)
    assert [client.post(CODE_URL).status_code for _ in range(6)] == [201] * 5 + [429]


def test_post_when_not_configured(auth_client, customer, settings):
    settings.WHATSAPP_BUSINESS_NUMBER = ""
    response = auth_client(customer).post(CODE_URL)
    assert response.status_code == 503
    assert response.json() == {"detail": "WhatsApp is not configured."}


def test_delete_unlinks(auth_client, customer, contact_factory):
    contact = contact_factory(user=customer, linked_at=timezone.now())
    User.objects.filter(pk=customer.pk).update(whatsapp_verified=True)
    assert auth_client(customer).delete(URL).status_code == 204
    contact.refresh_from_db()
    customer.refresh_from_db()
    assert contact.user is None and contact.linked_at is None and not customer.whatsapp_verified
    assert auth_client(customer).delete(URL).status_code == 204  # nothing linked: same answer


def test_anonymous_is_refused(api_client):
    assert api_client.get(URL).status_code == 401
    assert api_client.post(CODE_URL).status_code == 401
    assert api_client.delete(URL).status_code == 401


# --- In chat --------------------------------------------------------------------------------------


@pytest.fixture
def guest_with_cart(deliver_inbound, chat_model, shoe_catalog):
    chat_model.add([tool_call("add_to_cart", product_id=shoe_catalog.red.pk)], "Nimeongeza.")
    deliver_inbound(wa.text_message("red sneakers"))
    return WhatsAppContact.objects.get()


def test_valid_code_links_and_merges_the_cart(deliver_inbound, chat_model, graph, customer, guest_with_cart,
                                              shoe_catalog):
    Address.objects.create(user=customer, region="Mwanza", street="Kenyatta Rd 4", is_default=True)
    user_cart = Cart.objects.create(user=customer)
    services.add_item(user_cart, shoe_catalog.charger.pk, 1)
    code = new_code(customer)
    requests_before = len(chat_model.requests)

    deliver_inbound(wa.text_message(code))

    assert len(chat_model.requests) == requests_before  # handled before the assistant
    assert graph.texts[-1] == "Namba hii sasa imeunganishwa na akaunti yako."
    contact = WhatsAppContact.objects.get()
    customer.refresh_from_db()
    assert contact.user == customer and contact.linked_at and customer.whatsapp_verified
    conversation = contact.conversation
    assert conversation.user == customer and conversation.cart is None
    names = set(Cart.objects.get(user=customer).items.values_list("product__name", flat=True))
    assert names == {"Red Sneakers", "Phone Charger"}
    assert WhatsAppLinkCode.objects.get().used_by == contact

    # the conversation now acts as the customer (saved address, account cart)
    chat_model.add([tool_call("collect_guest_details")], "Sawa.")
    deliver_inbound(wa.text_message("tuma Mwanza"))
    assert Conversation.objects.get(pk=conversation.pk).checkout_details["region"] == "Mwanza"


@pytest.mark.parametrize("state", ["wrong", "expired", "used"])
def test_bad_codes_fail(deliver_inbound, graph, customer, contact_factory, state):
    contact_factory()
    code = new_code(customer)
    if state == "wrong":
        code = "LINK-ZZZZZZ" if code != "LINK-ZZZZZZ" else "LINK-YYYYYY"
    elif state == "expired":
        WhatsAppLinkCode.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    else:
        WhatsAppLinkCode.objects.update(used_at=timezone.now())
    deliver_inbound(wa.text_message(code))
    assert graph.texts[-1].startswith("Samahani, msimbo huo haufanyi kazi")
    assert WhatsAppContact.objects.get().user is None


def test_sixth_wrong_code_in_an_hour_is_not_checked(deliver_inbound, graph, customer, contact_factory):
    contact_factory()
    for n in range(5):
        deliver_inbound(wa.text_message(f"LINK-WRONG{n + 2}"[:11]))
    good = new_code(customer)
    deliver_inbound(wa.text_message(good))
    assert graph.texts[-1].startswith("Samahani, msimbo huo")
    assert WhatsAppContact.objects.get().user is None
    assert WhatsAppLinkCode.objects.get().used_at is None


def test_number_linked_to_someone_else(deliver_inbound, graph, customer, contact_factory):
    other = User.objects.create_user("juma", password="pw")
    contact_factory(user=other, linked_at=timezone.now())
    deliver_inbound(wa.text_message(new_code(customer)))
    assert graph.texts[-1] == "Namba hii tayari imeunganishwa na akaunti nyingine."
    assert WhatsAppContact.objects.get().user == other
    assert WhatsAppLinkCode.objects.get().used_at is not None


def test_previous_number_is_unlinked(deliver_inbound, customer, contact_factory):
    old = contact_factory(wa_id="255742000999", user=customer, linked_at=timezone.now())
    contact_factory()
    deliver_inbound(wa.text_message(new_code(customer)))
    old.refresh_from_db()
    assert old.user is None
    assert WhatsAppContact.objects.get(wa_id="255742000331").user == customer


def test_code_inside_a_sentence(deliver_inbound, customer, contact_factory):
    contact_factory()
    code = new_code(customer)
    deliver_inbound(wa.text_message(f"Habari, msimbo wangu ni {code.lower()} asante"))
    assert WhatsAppContact.objects.get().user == customer


def test_after_unlink_the_next_turn_is_a_guest(deliver_inbound, chat_model, auth_client, customer, graph,
                                               shoe_catalog, region, stakaba):
    # a guest order placed from WhatsApp, then link
    chat_model.add([tool_call("add_to_cart", product_id=shoe_catalog.red.pk),
                    tool_call("collect_guest_details", name="Asha", region="Dar es Salaam", street="Uhuru 1"),
                    tool_call("checkout", confirm=False)], "Muhtasari.")
    deliver_inbound(wa.text_message("nataka red sneakers"))
    prompt_id = graph.sent[-1]["interactive"]["action"]["buttons"][0]["reply"]["id"]
    deliver_inbound(wa.button_reply(prompt_id))
    deliver_inbound(wa.text_message(new_code(customer)))
    linked_conversation = WhatsAppContact.objects.get().conversation

    auth_client(customer).delete(URL)

    chat_model.add([tool_call("order_status")], "Hii hapa.")
    deliver_inbound(wa.text_message("oda yangu?"))
    contact = WhatsAppContact.objects.get()
    assert contact.user is None
    assert contact.conversation != linked_conversation
    assert contact.conversation.user is None and contact.conversation.cart is not None
    order_number = contact.orders.get().order.number
    assert order_number in chat_model.requests[-1]["messages"][-1]["content"]
