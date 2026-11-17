"""Rider WhatsApp templates and inbox entries (FR-019, FR-020, contracts/notifications.md)."""

import pytest

from apps.delivery import services
from apps.delivery.models import DeliveryNotification, RiderInboxEntry
from apps.whatsapp.models import WhatsAppContact

pytestmark = pytest.mark.django_db


def templates(graph):
    return [
        (body["to"], body["template"]["name"], body["template"]["language"]["code"],
         [p["text"] for p in body["template"].get("components", [{}])[0].get("parameters", [])])
        for body in graph.sent if body.get("type") == "template"
    ]


def test_assign_sends_the_job_template_and_an_inbox_entry(delivery, rider, admin_user, graph, run_commits):
    rider.preferred_language = "en"
    rider.save()
    run_commits(services.assign, delivery, rider, admin_user)
    order = delivery.order
    assert templates(graph) == [("255700000001", "delivery_assigned", "en",
                                 [order.number, "Dar es Salaam", "Mtaa wa Uhuru 12", "Amina Juma", "2"])]
    contact = WhatsAppContact.objects.get(phone="+255700000001")
    assert contact.wa_id == "255700000001"
    note = DeliveryNotification.objects.get(delivery=delivery)
    assert (note.kind, note.rider, note.attempt, note.state) == ("rider_assigned", rider, 1, "queued")
    assert note.outbound is not None and note.outbound.status == "sent"
    entry = RiderInboxEntry.objects.get(rider=rider)
    assert entry.kind == "assigned" and order.number in entry.title_sw and order.number in entry.title_en


def test_reassign_tells_both_riders(delivery, rider, rider2, admin_user, graph, run_commits):
    run_commits(services.assign, delivery, rider, admin_user)
    graph.sent.clear()
    run_commits(services.assign, delivery, rider2, admin_user)
    sent = {(to, name) for to, name, _, _ in templates(graph)}
    assert sent == {("255700000001", "delivery_removed"), ("255700000002", "delivery_assigned")}
    assert RiderInboxEntry.objects.filter(rider=rider).count() == 2


def test_unassign_and_cancel(delivery, rider, admin_user, graph, run_commits):
    run_commits(services.assign, delivery, rider, admin_user)
    run_commits(services.unassign, delivery, admin_user)
    run_commits(services.assign, delivery, rider, admin_user)  # given back: the rider hears it again
    run_commits(services.cancel_for_order, delivery.order)
    names = [name for _, name, _, _ in templates(graph)]
    assert names == ["delivery_assigned", "delivery_removed", "delivery_assigned", "delivery_cancelled"]
    assert list(DeliveryNotification.objects.filter(kind="rider_assigned").values_list("attempt", flat=True)) == [1, 2]
    assert set(RiderInboxEntry.objects.values_list("kind", flat=True)) == {"assigned", "removed", "cancelled"}


def test_rider_messages_ignore_the_customer_opt_out(delivery, rider, admin_user, graph, run_commits):
    WhatsAppContact.objects.create(wa_id="255700000001", phone="+255700000001", updates_allowed=False)
    run_commits(services.assign, delivery, rider, admin_user)
    assert [name for _, name, _, _ in templates(graph)] == ["delivery_assigned"]


def test_a_repeat_sends_nothing(delivery, rider, admin_user, graph, run_commits):
    run_commits(services.assign, delivery, rider, admin_user)
    run_commits(services.assign, delivery, rider, admin_user)
    assert len(templates(graph)) == 1


def test_a_send_failure_keeps_the_assignment(delivery, rider, admin_user, graph, run_commits):
    graph.fail_next(code=131026, transient=False)  # recipient not on WhatsApp
    run_commits(services.assign, delivery, rider, admin_user)
    delivery.refresh_from_db()
    assert delivery.status == "assigned"
    note = DeliveryNotification.objects.get(delivery=delivery)
    assert note.outbound.status == "failed"
