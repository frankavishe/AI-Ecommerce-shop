"""Common rider messages are answered by the server without the model (contracts/rider-tools.md "Server commands")."""

import pytest

from apps.ai.models import ChatMessage
from apps.delivery import services
from apps.delivery.models import Delivery, DeliveryNotification
from apps.delivery.rider_commands import parse
from apps.whatsapp import testing as wa
from apps.whatsapp.models import WhatsAppInboundMessage as Inbound

pytestmark = pytest.mark.django_db
RIDER_WA = "255700000001"


@pytest.mark.parametrize("text, intent, numbers, reason", [
    ("kazi zangu?", "jobs", [], ""),
    ("Kazi", "jobs", [], ""),
    ("my jobs", "jobs", [], ""),
    ("nimechukua mzigo wa K7P2QX23", "picked_up", ["K7P2QX23"], ""),
    ("nimechukua #k7p2qx23", "picked_up", ["K7P2QX23"], ""),
    ("niko njiani", "on_the_way", [], ""),
    ("nimefikisha 92BC3B36", "delivered", ["92BC3B36"], ""),
    ("delivered 92BC3B36", "delivered", ["92BC3B36"], ""),
    ("imeshindikana, mteja hapatikani", "failed", [], "mteja hapatikani"),
    ("imeshindikana 92BC3B36: mteja hapatikani", "failed", ["92BC3B36"], "mteja hapatikani"),
    ("imeshindikana", "failed", [], ""),
    ("niko off leo", "unavailable", [], ""),
    ("I'm not available", "unavailable", [], ""),
    ("niko tayari", "available", [], ""),
])
def test_parse(text, intent, numbers, reason):
    command = parse(text)
    assert (command.intent, command.numbers, command.reason) == (intent, numbers, reason)


@pytest.mark.parametrize("text", [
    "habari",
    "bei ya viatu ni ngapi?",
    "nimefikisha lakini imeshindikana kulipa",  # two commands: the model sorts it out
    "nimechukua " + "mzigo " * 20,  # too long
    "",
])
def test_parse_leaves_other_messages_to_the_model(text):
    assert parse(text) is None


def test_lower_case_word_is_a_number_only_when_it_is_the_riders_job():
    command = parse("nimechukua nachukua")
    assert command.numbers == [] and command.maybe == ["NACHUKUA"]


@pytest.fixture
def deliver(client, django_capture_on_commit_callbacks, settings):
    settings.WHATSAPP_VERIFY_TOKEN = "test-verify"

    def post(text, wa_id=RIDER_WA):
        with django_capture_on_commit_callbacks(execute=True):
            return wa.signed_post(client, wa.text_message(text, wa_id=wa_id))

    return post


@pytest.fixture
def assigned(make_order, pay, run_commits, rider, admin_user):
    def make():
        order = make_order()
        run_commits(pay, order)
        delivery = Delivery.objects.get(order=order)
        run_commits(services.assign, delivery, rider, admin_user)
        return delivery

    return make


def test_jobs_are_listed_without_the_model(deliver, chat_model, graph, assigned):
    job = assigned()
    deliver("kazi zangu?")
    assert chat_model.requests == []
    assert graph.texts[-1].startswith(f"Kazi zako (1):\n• {job.order.number}")
    reply = ChatMessage.objects.get(role=ChatMessage.Role.ASSISTANT)
    assert reply.tool_calls[0]["name"] == "my_jobs" and reply.steps == 0
    assert Inbound.objects.get().status == "answered"


def test_single_job_is_used_when_no_number_given(deliver, chat_model, graph, assigned):
    job = assigned()
    deliver("nimechukua mzigo")
    job.refresh_from_db()
    job.order.refresh_from_db()
    assert job.status == "picked_up" and job.order.status == "out_for_delivery"
    assert graph.texts[-1] == f"Sawa, oda {job.order.number} imechukuliwa."
    assert chat_model.requests == []


def test_several_jobs_and_no_number_asks_which(deliver, graph, assigned):
    first, second = assigned(), assigned()
    deliver("nimefikisha")
    text = graph.texts[-1]
    assert text.startswith("Una kazi zaidi ya moja")
    assert first.order.number in text and second.order.number in text
    assert set(Delivery.objects.values_list("status", flat=True)) == {"assigned"}


def test_delivered_twice_answers_already_and_notifies_once(deliver, graph, assigned):
    job = assigned()
    number = job.order.number
    deliver(f"nimefikisha {number}")
    sent = DeliveryNotification.objects.count()
    deliver(f"nimefikisha {number}")
    assert graph.texts[-2:] == [f"Asante! Oda {number} imefikishwa.", f"Oda {number} tayari iko: imefikishwa."]
    assert DeliveryNotification.objects.count() == sent


def test_another_riders_order_is_not_found(deliver, graph, assigned, rider2):
    job = assigned()
    deliver(f"nimefikisha {job.order.number}", wa_id="255700000002")
    assert graph.texts[-1] == f"Oda {job.order.number} haipo kwenye kazi zako."
    job.refresh_from_db()
    assert job.status == "assigned"


def test_failed_with_reason(deliver, assigned):
    job = assigned()
    deliver("nimechukua")
    deliver("imeshindikana, mteja hapatikani")
    job.refresh_from_db()
    assert job.status == "failed" and job.failure_reason == "mteja hapatikani"


def test_failed_without_reason_asks_for_it(deliver, graph, assigned):
    job = assigned()
    deliver("nimechukua")
    deliver("imeshindikana")
    assert "eleza kwa nini" in graph.texts[-1]
    job.refresh_from_db()
    assert job.status == "picked_up"


def test_other_messages_still_reach_the_model(deliver, chat_model, assigned):
    assigned()
    chat_model.add("Ninasaidia na usafirishaji tu. Wasiliana na msimamizi.")
    deliver("bei ya viatu ni ngapi?")
    assert len(chat_model.requests) == 1
