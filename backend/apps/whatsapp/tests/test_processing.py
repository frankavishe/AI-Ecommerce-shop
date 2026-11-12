import time
from datetime import timedelta
from unittest import mock

import pytest
from django.core.files.base import ContentFile
from django.utils import timezone

from apps.ai import agent, prompts
from apps.ai.clients import ModelUnavailable
from apps.ai.models import ChatMessage, Conversation
from apps.ai.testing import tool_call
from apps.catalog.models import ProductImage
from apps.whatsapp import tasks
from apps.whatsapp import testing as wa
from apps.whatsapp.models import WhatsAppContact, WhatsAppInboundMessage as Inbound

pytestmark = pytest.mark.django_db


def inbound_status(message_id):
    return Inbound.objects.get(wa_message_id=message_id).status


def test_new_number_gets_swahili_reply_with_db_products(deliver_inbound, chat_model, graph, shoe_catalog):
    chat_model.add([tool_call("search_products", query="viatu")],
                   "Tuna Red Sneakers kwa 45,000 TZS na Blue Sandals kwa 30,000 TZS.")
    deliver_inbound(wa.text_message("nataka viatu vyekundu", message_id="wamid.1"))

    contact = WhatsAppContact.objects.get()
    conversation = contact.conversation
    assert conversation.channel == Conversation.Channel.WHATSAPP
    assert conversation.language == "sw" and contact.language == "sw"
    assert conversation.cart is not None and conversation.user is None
    assert graph.texts == ["Tuna Red Sneakers kwa 45,000 TZS na Blue Sandals kwa 30,000 TZS."]
    assert graph.sent[0]["to"] == "255742000331"

    reply = conversation.messages.get(role=ChatMessage.Role.ASSISTANT)
    names = {p["name"] for p in reply.payload["products"]}
    assert names and "Old Boots" not in names  # inactive products never come back
    assert {p["price"] for p in reply.payload["products"] if p["name"] == "Red Sneakers"} == {"45000.00"}

    inbound = Inbound.objects.get()
    assert inbound.status == "answered" and inbound.processed_at is not None
    assert inbound.chat_message.text == "nataka viatu vyekundu"
    assert inbound.chat_message.payload["whatsapp"] == {"type": "text", "wa_message_id": "wamid.1"}


def test_follow_up_uses_history(deliver_inbound, chat_model):
    deliver_inbound(wa.text_message("nataka viatu"))
    deliver_inbound(wa.text_message("vyekundu"))
    assert {"role": "user", "content": "nataka viatu"} in chat_model.last_messages
    assert Conversation.objects.count() == 1


@pytest.fixture
def with_photos(shoe_catalog, png_bytes):
    for product, color in ((shoe_catalog.red, (255, 0, 0)), (shoe_catalog.blue, (0, 0, 255)),
                           (shoe_catalog.charger, (0, 0, 0))):
        ProductImage.objects.create(product=product, image=ContentFile(png_bytes(color), name="p.png"))
    return shoe_catalog


def test_up_to_three_product_photos_with_db_captions(deliver_inbound, chat_model, graph, with_photos, settings):
    catalog = with_photos
    calls = [tool_call("get_product", product_id=p.pk)
             for p in (catalog.red, catalog.heels, catalog.blue, catalog.charger)]
    chat_model.add(calls, "Phone Charger ni 15,000 TZS (bei ya ajabu 1 TZS).")
    deliver_inbound(wa.text_message("nionyeshe bidhaa"))

    images = graph.of_type("image")
    assert len(images) == 3  # Black Heels has no photo; the rest are capped at 3
    captions = [body["image"]["caption"] for body in images]
    assert captions[0] == "Phone Charger — 15,000 TZS"  # named in the reply text: first
    assert captions[1:] == ["Red Sneakers — 45,000 TZS", "Blue Sandals — 30,000 TZS"]
    assert all(body["image"]["id"].startswith("media.FAKE") for body in images)
    assert graph.sent[0]["type"] == "text"  # the reply text first, then photos

    settings.WHATSAPP_MAX_PRODUCT_PHOTOS = 1
    chat_model.add(calls, "Hizi hapa.")
    deliver_inbound(wa.text_message("tena"))
    assert len(graph.of_type("image")) == 4
    assert len(graph.uploads) == 3  # uploads are cached


def test_messages_are_processed_in_send_order(client, chat_model, contact_factory):
    now = int(time.time())
    with mock.patch("apps.whatsapp.tasks.drain_contact.delay"):
        for text, offset in (("tatu", 2), ("moja", 0), ("mbili", 1)):
            wa.signed_post(client, wa.text_message(text, sent_at=now + offset))
    tasks.drain_contact(WhatsAppContact.objects.get().pk)
    users = [r["messages"][-1]["content"] for r in chat_model.requests]
    assert users == ["moja", "mbili", "tatu"]


def test_drain_skips_when_lock_is_held(client, chat_model):
    with mock.patch("apps.whatsapp.tasks.drain_contact.delay"):
        wa.signed_post(client, wa.text_message("habari"))
    contact = WhatsAppContact.objects.get()
    with mock.patch("apps.whatsapp.tasks.advisory_lock") as lock:
        lock.return_value.__enter__.return_value = False
        assert tasks.drain_contact(contact.pk) == "busy"
    assert chat_model.requests == []


def test_stuck_processing_rows_are_picked_up_again(client, chat_model, settings):
    with mock.patch("apps.whatsapp.tasks.drain_contact.delay"):
        wa.signed_post(client, wa.text_message("habari", message_id="wamid.STUCK"))
    Inbound.objects.update(status="processing")
    contact = WhatsAppContact.objects.get()
    tasks.drain_contact(contact.pk)
    assert inbound_status("wamid.STUCK") == "processing"  # still within the grace period

    Inbound.objects.update(received_at=timezone.now() - timedelta(seconds=settings.AI_CHAT_TIMEOUT + 121))
    tasks.drain_contact(contact.pk)
    assert inbound_status("wamid.STUCK") == "answered"


def test_eleventh_message_in_a_minute_is_rate_limited(deliver_inbound, chat_model, graph):
    for n in range(12):
        deliver_inbound(wa.text_message(f"ujumbe {n}", message_id=f"wamid.R{n}"))
    assert len(chat_model.requests) == 10
    assert inbound_status("wamid.R10") == "rate_limited"
    assert inbound_status("wamid.R11") == "rate_limited"
    slow = [t for t in graph.texts if t.startswith("Unatuma ujumbe mwingi")]
    assert len(slow) == 1
    # the limited messages are still saved for staff
    conversation = WhatsAppContact.objects.get().conversation
    assert conversation.messages.filter(role="user", text="ujumbe 11").exists()


def test_daily_limit(deliver_inbound, chat_model, graph, settings):
    settings.WHATSAPP_RATE_PER_DAY = 3
    for n in range(4):
        deliver_inbound(wa.text_message(f"ujumbe {n}", message_id=f"wamid.D{n}"))
    assert len(chat_model.requests) == 3
    assert inbound_status("wamid.D3") == "rate_limited"
    assert sum(t.startswith("Unatuma") for t in graph.texts) == 1


def test_model_down_sends_fallback_and_saves_message(deliver_inbound, chat_model, graph):
    chat_model.add(ModelUnavailable("down"))
    deliver_inbound(wa.text_message("nataka simu", message_id="wamid.DOWN"))
    assert graph.texts == [prompts.FALLBACK["model_unavailable"]["sw"]]
    inbound = Inbound.objects.get()
    assert (inbound.status, inbound.error) == ("failed", "model_unavailable")
    assert inbound.chat_message.text == "nataka simu"


def test_unexpected_error_still_sends_fallback(deliver_inbound, chat_model, graph):
    with mock.patch("apps.whatsapp.processing.agent.handle_message", side_effect=RuntimeError("boom")):
        deliver_inbound(wa.text_message("habari", message_id="wamid.BOOM"))
    inbound = Inbound.objects.get()
    assert (inbound.status, inbound.error) == ("failed", "internal_error")
    assert graph.texts == [prompts.FALLBACK["model_unavailable"]["sw"]]


def test_message_older_than_a_day_is_recorded_not_answered(deliver_inbound, chat_model, graph):
    old = time.time() - 25 * 3600
    deliver_inbound(wa.text_message("habari ya zamani", sent_at=old, message_id="wamid.OLD"))
    assert inbound_status("wamid.OLD") == "recorded"
    assert chat_model.requests == [] and graph.sent == []
    assert ChatMessage.objects.filter(text="habari ya zamani").exists()


def test_timeout_sends_exactly_one_fallback(deliver_inbound, chat_model, graph, settings, monkeypatch):
    settings.AI_CHAT_TIMEOUT = 20
    clock = [1000.0]
    monkeypatch.setattr(agent, "_now", lambda: clock[0])

    def slow_model(messages, tools):
        clock[0] += 25
        return "jibu la kuchelewa"

    chat_model.add(slow_model)
    deliver_inbound(wa.text_message("nataka simu", message_id="wamid.SLOW"))
    assert graph.texts == [prompts.FALLBACK["timeout"]["sw"]]
    assert (Inbound.objects.get().status, Inbound.objects.get().error) == ("failed", "timeout")


def test_long_reply_is_split_in_order(deliver_inbound, chat_model, graph, settings):
    settings.WHATSAPP_TEXT_LIMIT = 40
    chat_model.add("Sehemu ya kwanza ya jibu hili.\n\nSehemu ya pili ya jibu hili.\n\nSehemu ya tatu.")
    deliver_inbound(wa.text_message("habari"))
    assert graph.texts == ["Sehemu ya kwanza ya jibu hili.", "Sehemu ya pili ya jibu hili.", "Sehemu ya tatu."]


def test_contact_language_follows_conversation(deliver_inbound, chat_model):
    chat_model.add("Hello! We have shoes.")
    deliver_inbound(wa.text_message("Hello, do you have red shoes please?"))
    contact = WhatsAppContact.objects.get()
    assert contact.conversation.language == "en"
    assert contact.language == "en"


def test_last_inbound_at_never_moves_backwards(deliver_inbound, chat_model):
    now = time.time()
    deliver_inbound(wa.text_message("ya sasa", sent_at=now, message_id="wamid.NOW"))
    latest = WhatsAppContact.objects.get().last_inbound_at
    deliver_inbound(wa.text_message("ya zamani kidogo", sent_at=now - 7200, message_id="wamid.EARLIER"))
    assert WhatsAppContact.objects.get().last_inbound_at == latest
    assert inbound_status("wamid.EARLIER") == "answered"


def test_unsupported_type_gets_help_text_without_model(deliver_inbound, chat_model, graph):
    deliver_inbound(wa.unsupported_message("sticker", message_id="wamid.STICKER"))
    assert chat_model.requests == []
    assert graph.texts == ["Ninaweza kusoma ujumbe wa maandishi, picha na sauti tu."]
    assert inbound_status("wamid.STICKER") == "rejected"
