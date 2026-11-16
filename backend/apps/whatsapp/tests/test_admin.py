"""US4: staff take over a WhatsApp conversation (contracts/admin-api.md)."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.ai.models import ChatMessage, Conversation
from apps.whatsapp import testing as wa
from apps.whatsapp.models import (
    WhatsAppContact,
    WhatsAppInboundMessage as Inbound,
    WhatsAppOrderNotification,
    WhatsAppOutboundMessage as Out,
)

pytestmark = pytest.mark.django_db


def reply_url(conversation):
    return f"/api/whatsapp/admin/conversations/{conversation.pk}/reply/"


@pytest.fixture
def flagged(deliver_inbound, chat_model, graph):
    """A WhatsApp conversation handed to staff, after one answered message."""
    chat_model.add("Karibu!")
    deliver_inbound(wa.text_message("habari", message_id="wamid.first"))
    contact = WhatsAppContact.objects.get()
    conversation = contact.conversation
    conversation.state = Conversation.State.NEEDS_HUMAN
    conversation.handoff_reason = "Shopper asked for a person"
    conversation.save()
    graph.sent.clear()
    return contact, conversation


@pytest.fixture
def staff(auth_client, admin_user):
    return auth_client(admin_user)


def test_flagged_conversation_records_without_replying(flagged, deliver_inbound, chat_model, graph):
    calls = len(chat_model.requests)
    deliver_inbound(wa.text_message("nataka kuongea na mtu", message_id="wamid.2"))
    assert graph.sent == []
    assert len(chat_model.requests) == calls
    inbound = Inbound.objects.get(wa_message_id="wamid.2")
    assert inbound.status == "recorded" and inbound.chat_message.text == "nataka kuongea na mtu"


def test_staff_reply_within_window(flagged, staff, admin_user, graph, django_capture_on_commit_callbacks):
    contact, conversation = flagged
    with django_capture_on_commit_callbacks(execute=True):
        response = staff.post(reply_url(conversation), {"text": "Habari Asha, nimeangalia oda yako."},
                              format="json")
    assert response.status_code == 202, response.content
    row = Out.objects.get(pk=response.json()["outbound_id"])
    assert response.json()["status"] == "queued"
    assert (row.trigger, row.staff_user, row.conversation) == ("staff", admin_user, conversation)
    assert graph.texts == ["Habari Asha, nimeangalia oda yako."]
    message = conversation.messages.get(role=ChatMessage.Role.STAFF)
    assert message.text == "Habari Asha, nimeangalia oda yako."
    conversation.refresh_from_db()
    assert conversation.state == Conversation.State.NEEDS_HUMAN  # staff release explicitly


def test_long_staff_reply_is_split(flagged, staff, graph, django_capture_on_commit_callbacks, settings):
    settings.WHATSAPP_TEXT_LIMIT = 50
    _, conversation = flagged
    text = "Sentensi ya kwanza ni ndefu kidogo. " * 4
    with django_capture_on_commit_callbacks(execute=True):
        response = staff.post(reply_url(conversation), {"text": text}, format="json")
    assert response.status_code == 202
    assert len(graph.texts) > 1
    assert " ".join(graph.texts).split() == text.split()


def test_window_closed_refuses_free_text(flagged, staff, graph, django_capture_on_commit_callbacks):
    contact, conversation = flagged
    contact.last_inbound_at = timezone.now() - timedelta(hours=25)
    contact.save()
    with django_capture_on_commit_callbacks(execute=True):
        response = staff.post(reply_url(conversation), {"text": "Habari"}, format="json")
    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "window_closed" and body["templates"] == ["follow_up"]
    assert graph.sent == [] and not Out.objects.filter(trigger="staff").exists()
    assert not conversation.messages.filter(role=ChatMessage.Role.STAFF).exists()


def test_follow_up_template_with_window_closed(flagged, staff, graph, settings,
                                               django_capture_on_commit_callbacks):
    settings.WHATSAPP_TEMPLATE_FOLLOW_UP = "follow_up_v2"
    contact, conversation = flagged
    contact.last_inbound_at = timezone.now() - timedelta(days=3)
    contact.save()
    with django_capture_on_commit_callbacks(execute=True):
        response = staff.post(reply_url(conversation), {"template": "follow_up"}, format="json")
    assert response.status_code == 202, response.content
    assert graph.sent[-1]["type"] == "template"
    assert graph.sent[-1]["template"]["name"] == "follow_up_v2"
    assert Out.objects.filter(kind="template").get().trigger == "staff"
    assert conversation.messages.get(role=ChatMessage.Role.STAFF).text


@pytest.mark.parametrize("body", [{}, {"text": ""}, {"text": "   "}, {"text": "x" * (4096 * 3 + 1)},
                                  {"template": "something_else"}, {"text": "hi", "template": "follow_up"}])
def test_bad_requests(flagged, staff, body):
    _, conversation = flagged
    assert staff.post(reply_url(conversation), body, format="json").status_code == 400
    assert not Out.objects.filter(trigger="staff").exists()


def test_not_whatsapp_conversation(staff):
    conversation = Conversation.objects.create()
    response = staff.post(reply_url(conversation), {"text": "hi"}, format="json")
    assert response.status_code == 400 and response.json()["code"] == "not_whatsapp"


def test_unknown_conversation_is_404(staff):
    response = staff.post("/api/whatsapp/admin/conversations/00000000-0000-0000-0000-000000000000/reply/",
                          {"text": "hi"}, format="json")
    assert response.status_code == 404


def test_permissions(flagged, auth_client, customer, api_client):
    _, conversation = flagged
    rider = User.objects.create_user("rider9", password="pw", role=User.Role.RIDER)
    assert auth_client(customer).post(reply_url(conversation), {"text": "hi"}, format="json").status_code == 403
    assert auth_client(rider).post(reply_url(conversation), {"text": "hi"}, format="json").status_code == 403
    assert api_client.post(reply_url(conversation), {"text": "hi"}, format="json").status_code == 401
    assert auth_client(customer).get("/api/whatsapp/admin/outbound/").status_code == 403
    assert api_client.get("/api/whatsapp/admin/outbound/").status_code == 401


def test_release_lets_the_assistant_answer_again(flagged, staff, deliver_inbound, chat_model, graph):
    _, conversation = flagged
    assert staff.post(f"/api/ai/admin/conversations/{conversation.pk}/release/").status_code == 200
    chat_model.add("Nimerudi, nikusaidie nini?")
    deliver_inbound(wa.text_message("habari tena", message_id="wamid.3"))
    assert graph.texts == ["Nimerudi, nikusaidie nini?"]


def test_admin_list_filters_by_channel_and_shows_whatsapp(flagged, staff):
    contact, conversation = flagged
    Conversation.objects.create(state=Conversation.State.NEEDS_HUMAN)  # a web one

    response = staff.get("/api/ai/admin/conversations/?channel=whatsapp&state=needs_human")
    assert response.status_code == 200
    results = response.json()["results"]
    assert [item["id"] for item in results] == [str(conversation.pk)]
    block = results[0]["whatsapp"]
    assert block["number"] == "+255742000331" and block["profile_name"] == "Asha"
    assert block["window_open"] is True and block["window_closes_at"]

    web = staff.get("/api/ai/admin/conversations/?channel=api").json()["results"]
    assert len(web) == 1 and web[0]["whatsapp"] is None


def test_admin_list_has_no_n_plus_one(flagged, staff, django_assert_max_num_queries):
    for n in range(5):
        contact = WhatsAppContact.objects.create(wa_id=f"25574200100{n}", phone=f"+25574200100{n}",
                                                 last_inbound_at=timezone.now())
        contact.conversation = Conversation.objects.create(channel=Conversation.Channel.WHATSAPP)
        contact.save()
    with django_assert_max_num_queries(6):
        response = staff.get("/api/ai/admin/conversations/?channel=whatsapp")
    assert len(response.json()["results"]) == 6
    assert all(item["whatsapp"] for item in response.json()["results"])


def test_old_conversation_still_shows_its_number(flagged, staff):
    """After a 7-day reset the contact points at a new conversation; the old one keeps its number."""
    contact, old = flagged
    contact.conversation = Conversation.objects.create(channel=Conversation.Channel.WHATSAPP)
    contact.save()
    detail = staff.get(f"/api/ai/admin/conversations/{old.pk}/").json()
    assert detail["whatsapp"]["number"] == "+255742000331"


def test_detail_shows_staff_messages_and_voice_transcript(flagged, staff, deliver_inbound, graph, speech,
                                                          django_capture_on_commit_callbacks):
    _, conversation = flagged
    graph.media["media.voice"] = (b"OggS-voice", "audio/ogg", 10)
    speech.add({"text": "nataka kurudisha viatu", "language": "sw", "duration": 2.0})
    deliver_inbound(wa.audio_message("media.voice", message_id="wamid.voice"))
    with django_capture_on_commit_callbacks(execute=True):
        staff.post(reply_url(conversation), {"text": "Sawa, tutakusaidia."}, format="json")

    messages = staff.get(f"/api/ai/admin/conversations/{conversation.pk}/").json()["messages"]
    roles = [m["role"] for m in messages]
    assert "staff" in roles
    voice = next(m for m in messages if m["payload"].get("whatsapp", {}).get("type") == "audio")
    assert voice["payload"]["whatsapp"]["transcript"] == "nataka kurudisha viatu"


def test_outbound_list_shows_failures(flagged, staff, graph, make_order,
                                      django_capture_on_commit_callbacks):
    contact, conversation = flagged
    graph.fail_next(131000, transient=False)
    with django_capture_on_commit_callbacks(execute=True):
        staff.post(reply_url(conversation), {"text": "Habari"}, format="json")
    order = make_order(phone=contact.phone)
    failed = Out.objects.get(trigger="staff")
    WhatsAppOrderNotification.objects.create(order=order, status="paid", outbound=failed, state="failed")

    response = staff.get("/api/whatsapp/admin/outbound/?status=failed")
    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) == 1
    item = results[0]
    assert item["status"] == "failed" and item["error_code"] == "131000"
    assert item["contact_number"] == "+255742000331" and item["order_number"] == order.number
    assert {"id", "kind", "trigger", "text", "error", "attempts", "created_at"} <= item.keys()

    assert staff.get("/api/whatsapp/admin/outbound/?status=delivered").json()["results"] == []
    assert len(staff.get(f"/api/whatsapp/admin/outbound/?contact={contact.pk}").json()["results"]) == 2
    assert staff.get("/api/whatsapp/admin/outbound/?contact=999999").json()["results"] == []


def test_flagged_photo_is_kept_for_staff_without_a_reply(flagged, deliver_inbound, chat_model, graph, png_bytes,
                                                         settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    _, conversation = flagged
    calls = len(chat_model.requests)
    graph.add_media("media.photo", png_bytes((200, 10, 10)), mime="image/png")
    deliver_inbound(wa.image_message("media.photo", caption="hii je?", mime="image/png", message_id="wamid.ph"))
    assert graph.sent == [] and len(chat_model.requests) == calls
    inbound = Inbound.objects.get(wa_message_id="wamid.ph")
    assert inbound.status == "recorded"
    assert inbound.chat_message.image and inbound.chat_message.text == "hii je?"
