"""FR-007a: a WhatsApp number starts a fresh conversation after 7 days of silence."""

import time
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.ai.models import Conversation
from apps.orders import services
from apps.orders.models import Cart
from apps.whatsapp import testing as wa
from apps.whatsapp.models import WhatsAppContact, WhatsAppOrder

pytestmark = pytest.mark.django_db

DAY = 24 * 3600


@pytest.fixture
def old_contact(contact_factory, make_product, make_order):
    """A number last heard from 8 days ago, with a guest cart and a placed order."""
    cart = Cart.objects.create()
    conversation = Conversation.objects.create(
        channel=Conversation.Channel.WHATSAPP, cart=cart, language="sw",
        checkout_details={"name": "Asha", "phone": "+255742000331"},
    )
    contact = contact_factory(conversation=conversation,
                              last_inbound_at=timezone.now() - timedelta(days=8))
    keep = make_product(name="Red Sneakers", stock=5)
    gone = make_product(name="Old Boots", stock=5)
    short = make_product(name="Black Heels", stock=5)
    for product, qty in ((keep, 1), (gone, 1), (short, 3)):
        services.add_item(cart, product.pk, qty)
    gone.is_active = False
    gone.save()
    short.stock = 2
    short.save()
    order = make_order()
    conversation.last_order = order
    conversation.save()
    WhatsAppOrder.objects.create(order=order, contact=contact)
    return contact


def test_after_seven_days_a_new_conversation_starts(deliver_inbound, chat_model, graph, old_contact):
    old = old_contact.conversation
    chat_model.add("Karibu tena!")
    deliver_inbound(wa.text_message("habari"))

    contact = WhatsAppContact.objects.get()
    new = contact.conversation
    assert new.pk != old.pk
    assert new.channel == Conversation.Channel.WHATSAPP
    assert new.cart_id == old.cart_id
    assert [item.product.name for item in new.cart.items.select_related("product")] == ["Red Sneakers"]
    assert new.checkout_details == {} and new.last_order is None and new.pending_checkout_at is None
    assert WhatsAppOrder.objects.filter(contact=contact).count() == 1
    assert graph.texts[0] == (
        "Karibu tena! Bidhaa hizi hazipatikani tena na zimeondolewa kwenye kikapu: Old Boots, Black Heels."
    )
    assert graph.texts[1] == "Karibu tena!"
    # the old history is not sent to the model
    assert chat_model.last_messages[1:] == [{"role": "user", "content": "habari"}]


def test_no_note_when_nothing_was_removed(deliver_inbound, chat_model, graph, contact_factory):
    conversation = Conversation.objects.create(channel="whatsapp", cart=Cart.objects.create())
    contact_factory(conversation=conversation, last_inbound_at=timezone.now() - timedelta(days=9))
    chat_model.add("Karibu!")
    deliver_inbound(wa.text_message("habari"))
    assert graph.texts == ["Karibu!"]
    assert WhatsAppContact.objects.get().conversation_id != conversation.pk


def test_under_seven_days_keeps_the_conversation(deliver_inbound, chat_model, old_contact):
    old_contact.last_inbound_at = timezone.now() - timedelta(days=6)
    old_contact.save()
    deliver_inbound(wa.text_message("habari"))
    assert WhatsAppContact.objects.get().conversation_id == old_contact.conversation_id


def test_needs_human_conversation_is_never_reset(deliver_inbound, chat_model, graph, old_contact):
    conversation = old_contact.conversation
    conversation.state = Conversation.State.NEEDS_HUMAN
    conversation.save()
    deliver_inbound(wa.text_message("bado nasubiri"))
    contact = WhatsAppContact.objects.get()
    assert contact.conversation_id == conversation.pk
    assert chat_model.requests == [] and graph.sent == []
    assert conversation.messages.filter(text="bado nasubiri").exists()


def test_purged_conversation_is_replaced(deliver_inbound, chat_model, old_contact):
    old_contact.last_inbound_at = timezone.now() - timedelta(hours=1)
    old_contact.save()
    old_contact.conversation.delete()
    chat_model.add("Karibu!")
    deliver_inbound(wa.text_message("habari", sent_at=time.time()))
    contact = WhatsAppContact.objects.get()
    assert contact.conversation is not None
    assert contact.conversation.messages.filter(text="habari").exists()
