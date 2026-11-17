"""A rider's WhatsApp number is served by the rider assistant (FR-014, FR-018, research R6)."""

import pytest

from apps.ai.models import ChatMessage, Conversation
from apps.ai.testing import tool_call
from apps.delivery import services
from apps.delivery.models import Delivery
from apps.whatsapp import testing as wa
from apps.whatsapp.models import WhatsAppContact
from apps.whatsapp.models import WhatsAppInboundMessage as Inbound

pytestmark = pytest.mark.django_db
RIDER_WA = "255700000001"


@pytest.fixture
def deliver_inbound(client, django_capture_on_commit_callbacks, settings):
    settings.WHATSAPP_APP_SECRET = "test-secret"
    settings.WHATSAPP_VERIFY_TOKEN = "test-verify"

    def post(payload):
        with django_capture_on_commit_callbacks(execute=True):
            return wa.signed_post(client, payload)

    return post


@pytest.fixture
def job(delivery, rider, admin_user, run_commits):
    run_commits(services.assign, delivery, rider, admin_user)
    return delivery


def tool_names(request):
    return {tool["function"]["name"] for tool in request["tools"]}


def test_rider_gets_rider_tools_and_prompt(deliver_inbound, chat_model, graph, rider, job):
    number = job.order.number
    chat_model.add([tool_call("update_delivery", order_number=number, status="delivered")],
                   "Garbled model text that the rider never sees.")
    # free-form wording (not a server command), so the model picks the tool
    deliver_inbound(wa.text_message(f"mteja ameshapokea mzigo wa {number}", wa_id=RIDER_WA, message_id="wamid.R1"))

    request = chat_model.requests[0]
    assert tool_names(request) == {"my_jobs", "job_details", "update_delivery", "set_availability"}
    assert "rider" in chat_model.system_prompt(0).lower()
    assert graph.texts == [f"Asante! Oda {number} imefikishwa."]  # the server's fixed text
    job.refresh_from_db()
    job.order.refresh_from_db()
    assert job.status == "delivered" and job.order.status == "delivered"
    contact = WhatsAppContact.objects.get(phone="+255700000001")
    assert contact.conversation.user == rider
    reply = contact.conversation.messages.get(role=ChatMessage.Role.ASSISTANT)
    assert reply.tool_calls[0]["name"] == "update_delivery" and reply.tool_calls[0]["ok"] is True
    assert Inbound.objects.get(wa_message_id="wamid.R1").status == "answered"


def test_customer_numbers_keep_customer_tools(deliver_inbound, chat_model, rider):
    deliver_inbound(wa.text_message("nataka viatu"))
    names = tool_names(chat_model.requests[0])
    assert "search_products" in names and "my_jobs" not in names


@pytest.mark.parametrize("change", ["deactivated", "no_profile", "not_rider"])
def test_former_riders_are_customers(deliver_inbound, chat_model, rider, change):
    if change == "deactivated":
        rider.is_active = False
        rider.save()
    elif change == "no_profile":
        rider.rider_profile.delete()
    else:
        rider.role = "customer"
        rider.save()
    deliver_inbound(wa.text_message("kazi zangu?", wa_id=RIDER_WA))
    names = tool_names(chat_model.requests[0])
    assert "my_jobs" not in names and "search_products" in names


@pytest.mark.parametrize("word", ["STOP", "acha"])
def test_rider_stop_keeps_job_messages(deliver_inbound, chat_model, graph, rider, word):
    deliver_inbound(wa.text_message(word, wa_id=RIDER_WA))
    assert chat_model.requests == []
    assert graph.texts == ["Wewe ni msafirishaji: ujumbe wa kazi hauwezi kuzimwa. Muombe msimamizi akuondoe."]
    assert WhatsAppContact.objects.get(phone="+255700000001").updates_allowed is True


def test_staff_takeover_silences_the_assistant(deliver_inbound, chat_model, graph, rider):
    deliver_inbound(wa.text_message("habari", wa_id=RIDER_WA))
    conversation = WhatsAppContact.objects.get(phone="+255700000001").conversation
    conversation.state = Conversation.State.NEEDS_HUMAN
    conversation.save()
    graph.sent.clear()
    calls = len(chat_model.requests)
    deliver_inbound(wa.text_message("niko njiani", wa_id=RIDER_WA))
    assert len(chat_model.requests) == calls and graph.texts == []


def test_rider_voice_note(deliver_inbound, chat_model, graph, speech, rider, job):
    number = job.order.number
    speech.add({"text": f"nimechukua mzigo wa {number}", "language": "swahili", "duration": 3})
    graph.add_media("VOICE", b"OggS-fake-voice", "audio/ogg; codecs=opus")
    chat_model.add([tool_call("update_delivery", order_number=number, status="picked_up")], "Sawa.")
    deliver_inbound(wa.audio_message("VOICE", wa_id=RIDER_WA))
    assert Delivery.objects.get(pk=job.pk).status == "picked_up"
    assert "my_jobs" in tool_names(chat_model.requests[0])


@pytest.fixture
def speech():
    from apps.ai import clients
    from apps.ai.testing import FakeSpeech

    fake = FakeSpeech()
    clients.use_fakes(speech=fake)
    yield fake
    clients.use_fakes(speech=None)


def test_admin_sees_rider_conversations_flagged(deliver_inbound, chat_model, rider, auth_client, admin_user):
    deliver_inbound(wa.text_message("kazi zangu?", wa_id=RIDER_WA))
    deliver_inbound(wa.text_message("nataka viatu"))
    rows = auth_client(admin_user).get("/api/ai/admin/conversations/").json()["results"]
    assert sorted(row["is_rider"] for row in rows) == [False, True]
