"""US5: order updates on WhatsApp (T052, research R14)."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.orders import services as orders
from apps.orders.models import Order, OrderEvent
from apps.orders.tasks import expire_unpaid_orders
from apps.payments import services as payments
from apps.whatsapp import outbound, tasks
from apps.whatsapp import testing as wa
from apps.whatsapp.models import WhatsAppContact, WhatsAppOrder, WhatsAppOrderNotification as Note
from apps.whatsapp.models import WhatsAppInboundMessage as Inbound, WhatsAppOutboundMessage as Out
from apps.whatsapp.texts import format_tzs

pytestmark = pytest.mark.django_db

WEBHOOK = "/api/payments/stakaba/webhook/hook-secret/"
S = Order.Status
SYSTEM = OrderEvent.Source.SYSTEM


@pytest.fixture
def run_commits(django_capture_on_commit_callbacks):
    """Run on-commit work (the notify task, then the deliver task) like a worker would."""

    def run(fn, *args, **kwargs):
        with django_capture_on_commit_callbacks(execute=True):
            return fn(*args, **kwargs)

    return run


@pytest.fixture
def contact(contact_factory):
    return contact_factory(profile_name="Asha")


@pytest.fixture
def wa_order(make_order, contact):
    order = make_order(phone=contact.phone)
    WhatsAppOrder.objects.create(order=order, contact=contact)
    return order


def templates(graph):
    return [body["template"] for body in graph.of_type("template")]


def params(template):
    return [p["text"] for p in template["components"][0]["parameters"]]


def test_paid_through_the_payment_webhook_sends_one_template(wa_order, api_client, stakaba, graph, run_commits):
    payment, error = payments.start_payment(wa_order)
    assert error is None
    for _ in range(5):  # replays (US5-3, SC-002)
        response = run_commits(api_client.post, WEBHOOK, stakaba.record(payment.provider_ref, 93000), format="json")
        assert response.status_code == 200
    wa_order.refresh_from_db()
    assert wa_order.status == S.PAID

    sent = templates(graph)
    assert len(sent) == 1
    assert sent[0]["name"] == "order_paid" and sent[0]["language"]["code"] == "sw"
    assert params(sent[0]) == [wa_order.number, format_tzs(wa_order.total)]
    note = Note.objects.get(order=wa_order)
    assert (note.status, note.state) == ("paid", "sent")
    assert note.outbound.trigger == "order_update" and note.outbound.status == "sent"


def test_notify_task_is_idempotent(wa_order, graph, run_commits):
    run_commits(orders.transition, wa_order, S.PAID, SYSTEM)
    run_commits(tasks.notify_order_status, wa_order.pk, "paid")
    run_commits(tasks.notify_order_status, wa_order.pk, "paid")
    assert len(templates(graph)) == 1 and Note.objects.count() == 1


def test_out_for_delivery_with_window_closed_uses_the_contact_language(wa_order, contact, graph, run_commits,
                                                                        settings):
    settings.WHATSAPP_TEMPLATE_ORDER_OUT_FOR_DELIVERY = "ofd_v1"
    contact.language = "en"
    contact.last_inbound_at = timezone.now() - timedelta(days=3)
    contact.save()
    for status in (S.PAID, S.PROCESSING, S.OUT_FOR_DELIVERY):
        run_commits(orders.transition, wa_order, status, SYSTEM)

    sent = templates(graph)
    assert [t["name"] for t in sent] == ["order_paid", "ofd_v1"]  # processing sends nothing
    assert sent[1]["language"]["code"] == "en" and params(sent[1]) == [wa_order.number]


@pytest.mark.parametrize("path, name", [
    ((S.PAID, S.PROCESSING, S.OUT_FOR_DELIVERY, S.DELIVERED), "order_delivered"),
    ((S.CANCELLED,), "order_cancelled"),
])
def test_delivered_and_cancelled(wa_order, graph, run_commits, path, name):
    for status in path:
        run_commits(orders.transition, wa_order, status, SYSTEM)
    assert templates(graph)[-1]["name"] == name


def test_expired_by_the_expiry_task(wa_order, graph, run_commits):
    Order.objects.filter(pk=wa_order.pk).update(expires_at=timezone.now() - timedelta(minutes=1))
    assert run_commits(expire_unpaid_orders) == 1
    assert [t["name"] for t in templates(graph)] == ["order_expired"]


def test_web_order_gets_nothing(make_order, contact, graph, run_commits):
    order = make_order(phone=contact.phone)  # same phone, but not placed on WhatsApp
    run_commits(orders.transition, order, S.PAID, SYSTEM)
    assert graph.sent == [] and not Note.objects.exists()


def test_updates_off_skips(wa_order, contact, graph, run_commits):
    contact.updates_allowed = False
    contact.save()
    run_commits(orders.transition, wa_order, S.PAID, SYSTEM)
    assert graph.sent == []
    assert Note.objects.get(order=wa_order).state == "skipped"


@pytest.mark.parametrize("word", ["STOP", "acha", " Sitaki ", "unsubscribe"])
def test_stop_turns_updates_off_without_the_model(contact, deliver_inbound, chat_model, graph, word):
    deliver_inbound(wa.text_message(word, message_id="wamid.stop"))
    contact.refresh_from_db()
    assert contact.updates_allowed is False
    assert chat_model.requests == []
    assert graph.texts == ["Sawa, hutapokea taarifa za oda tena. Tuma ANZA kuziwasha."]
    assert Inbound.objects.get(wa_message_id="wamid.stop").status == "answered"


@pytest.mark.parametrize("word", ["START", "anza"])
def test_start_turns_updates_back_on(contact, deliver_inbound, chat_model, graph, word):
    contact.updates_allowed = False
    contact.save()
    deliver_inbound(wa.text_message(word))
    contact.refresh_from_db()
    assert contact.updates_allowed is True and chat_model.requests == []
    assert graph.texts == ["Taarifa za oda zimewashwa."]


def test_stop_inside_a_sentence_goes_to_the_assistant(contact, deliver_inbound, chat_model):
    chat_model.add("Sawa.")
    deliver_inbound(wa.text_message("acha nifikirie kwanza"))
    contact.refresh_from_db()
    assert contact.updates_allowed is True and len(chat_model.requests) == 1


def test_send_failure_retries_then_shows_for_staff(wa_order, graph, django_capture_on_commit_callbacks,
                                                    auth_client, admin_user):
    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        orders.transition(wa_order, S.PAID, SYSTEM)
    with django_capture_on_commit_callbacks(execute=False):  # keep the deliver task queued
        for callback in callbacks:
            callback()
    note = Note.objects.get(order=wa_order)
    row = note.outbound
    assert (note.state, row.status) == ("sending", "queued")

    graph.fail_next(131000, transient=True)
    assert outbound.deliver_batch(row.batch) == "retry"
    note.refresh_from_db()
    wa_order.refresh_from_db()
    assert note.state == "sending" and wa_order.status == S.PAID  # the order is never touched

    graph.fail_next(131000, transient=True)
    assert outbound.deliver_batch(row.batch, last_attempt=True) == "done"
    note.refresh_from_db()
    assert note.state == "failed" and Out.objects.get(pk=row.pk).status == "failed"
    wa_order.refresh_from_db()
    assert wa_order.status == S.PAID

    listed = auth_client(admin_user).get("/api/whatsapp/admin/outbound/?status=failed").json()["results"]
    assert [item["order_number"] for item in listed] == [wa_order.number]


def test_contact_deleted_order_link_is_safe(wa_order, contact, graph, run_commits):
    WhatsAppContact.objects.filter(pk=contact.pk).delete()  # cascades the WhatsAppOrder
    run_commits(orders.transition, wa_order, S.PAID, SYSTEM)
    assert graph.sent == []
