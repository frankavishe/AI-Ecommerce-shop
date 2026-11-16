from datetime import timedelta
from unittest import mock

import pytest
from django.core.files.base import ContentFile
from django.utils import timezone

from apps.catalog.models import ProductImage
from apps.whatsapp import outbound, tasks
from apps.whatsapp.models import (
    WhatsAppMediaUpload, WhatsAppOrderNotification, WhatsAppOutboundMessage as Out,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def contact(contact_factory):
    return contact_factory()


def statuses(batch):
    return list(Out.objects.filter(batch=batch).order_by("position").values_list("status", flat=True))


def test_window_closed_raises_and_stores_nothing(contact):
    contact.last_inbound_at = timezone.now() - timedelta(hours=25)
    contact.save()
    with pytest.raises(outbound.WindowClosed):
        outbound.queue_text(contact, "Habari", trigger=Out.Trigger.ASSISTANT)
    with pytest.raises(outbound.WindowClosed):
        outbound.queue_buttons(contact, "Thibitisha?", [("confirm:x", "Thibitisha")],
                               trigger=Out.Trigger.ASSISTANT)
    assert not Out.objects.exists()


def test_window_never_opened_is_closed(contact):
    contact.last_inbound_at = None
    contact.save()
    with pytest.raises(outbound.WindowClosed):
        outbound.queue_text(contact, "Habari", trigger=Out.Trigger.SYSTEM)


def test_template_sends_with_window_closed(contact, graph):
    contact.last_inbound_at = timezone.now() - timedelta(days=3)
    contact.language = "en"
    contact.save()
    row = outbound.queue_template(contact, "order_paid", ["ORD-1", "93,000"], trigger=Out.Trigger.ORDER_UPDATE)
    assert outbound.deliver_batch(row.batch) == "done"
    body = graph.sent[0]
    assert body["type"] == "template"
    assert body["to"] == contact.wa_id
    assert body["template"]["name"] == "order_paid"
    assert body["template"]["language"] == {"code": "en"}
    assert [p["text"] for p in body["template"]["components"][0]["parameters"]] == ["ORD-1", "93,000"]
    row.refresh_from_db()
    assert row.status == Out.Status.SENT and row.wa_message_id == "wamid.FAKE1" and row.attempts == 1


def test_batch_keeps_order(contact, graph):
    rows = outbound.queue_text(contact, "First part.\n\nSecond part.", trigger=Out.Trigger.ASSISTANT, limit=15)
    batch = rows[0].batch
    outbound.queue_buttons(contact, "Thibitisha?", [("confirm:1", "Thibitisha"), ("change:1", "Badilisha")],
                           trigger=Out.Trigger.ASSISTANT, batch=batch)
    assert outbound.deliver_batch(batch) == "done"
    assert graph.texts == ["First part.", "Second part."]
    assert graph.sent[2]["type"] == "interactive"
    buttons = graph.sent[2]["interactive"]["action"]["buttons"]
    assert [b["reply"]["id"] for b in buttons] == ["confirm:1", "change:1"]
    assert statuses(batch) == ["sent", "sent", "sent"]


def test_flush_queues_delivery_on_commit(contact, graph, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        rows = outbound.queue_text(contact, "Habari", trigger=Out.Trigger.ASSISTANT)
        outbound.flush(rows[0].batch)
        assert graph.sent == []
    assert graph.texts == ["Habari"]


def test_transient_error_retries_rest_of_batch(contact, graph):
    rows = outbound.queue_text(contact, "One.\n\nTwo.\n\nThree.", trigger=Out.Trigger.ASSISTANT, limit=6)
    batch = rows[0].batch
    graph.fail_next(code=131016, transient=True, after=1)  # the 1st goes out, the 2nd fails once
    assert outbound.deliver_batch(batch) == "retry"
    assert statuses(batch) == ["sent", "queued", "queued"]
    second = Out.objects.get(batch=batch, position=1)
    assert second.attempts == 1 and second.error_code == "131016"

    assert outbound.deliver_batch(batch) == "done"
    assert statuses(batch) == ["sent", "sent", "sent"]


def test_task_retry_countdowns_then_fails(contact, graph):
    rows = outbound.queue_text(contact, "Habari", trigger=Out.Trigger.ASSISTANT)
    batch = str(rows[0].batch)
    countdowns = []

    class Retry(Exception):
        pass

    def fake_retry(countdown=None, **kw):
        countdowns.append(countdown)
        return Retry()

    with mock.patch.object(tasks.deliver, "retry", side_effect=fake_retry):
        for retries in range(3):
            graph.fail_next(code=130429, transient=True)
            tasks.deliver.push_request(retries=retries, is_eager=False)
            try:
                with pytest.raises(Retry):
                    tasks.deliver.run(batch)
            finally:
                tasks.deliver.pop_request()
        assert countdowns == [10, 60, 300]
        assert statuses(batch) == ["queued"]

        graph.fail_next(code=130429, transient=True)
        tasks.deliver.push_request(retries=3, is_eager=False)
        try:
            assert tasks.deliver.run(batch) == "done"
        finally:
            tasks.deliver.pop_request()
    row = Out.objects.get(batch=batch)
    assert row.status == Out.Status.FAILED and row.attempts == 4 and row.error_code == "130429"


def test_eager_task_does_not_retry(contact, graph):
    rows = outbound.queue_text(contact, "Habari", trigger=Out.Trigger.ASSISTANT)
    graph.fail_next(code=130429, transient=True)
    tasks.deliver.delay(str(rows[0].batch))
    assert statuses(rows[0].batch) == ["failed"]


def test_notification_follows_outbound_row(contact, graph, make_order):
    order = make_order()
    sent_row = outbound.queue_template(contact, "order_paid", ["A"], trigger=Out.Trigger.ORDER_UPDATE)
    note = WhatsAppOrderNotification.objects.create(order=order, status="paid", outbound=sent_row)
    outbound.deliver_batch(sent_row.batch)
    note.refresh_from_db()
    assert note.state == WhatsAppOrderNotification.State.SENT

    failed_row = outbound.queue_template(contact, "order_delivered", ["A"], trigger=Out.Trigger.ORDER_UPDATE)
    note2 = WhatsAppOrderNotification.objects.create(order=order, status="delivered", outbound=failed_row)
    graph.fail_next(code=132001, transient=False)
    outbound.deliver_batch(failed_row.batch)
    note2.refresh_from_db()
    assert note2.state == WhatsAppOrderNotification.State.FAILED


def test_recipient_error_fails_row_and_skips_rest(contact, graph):
    rows = outbound.queue_text(contact, "One.\n\nTwo.\n\nThree.", trigger=Out.Trigger.ASSISTANT, limit=6)
    graph.fail_next(code=131026, transient=False, title="Message undeliverable")
    assert outbound.deliver_batch(rows[0].batch) == "done"
    assert statuses(rows[0].batch) == ["failed", "skipped", "skipped"]
    first = Out.objects.get(batch=rows[0].batch, position=0)
    assert first.error_code == "131026" and "undeliverable" in first.error
    assert graph.sent == []


def test_other_permanent_error_fails_row_and_continues(contact, graph):
    rows = outbound.queue_text(contact, "One.\n\nTwo.", trigger=Out.Trigger.ASSISTANT, limit=6)
    graph.fail_next(code=100, transient=False)
    outbound.deliver_batch(rows[0].batch)
    assert statuses(rows[0].batch) == ["failed", "sent"]


def test_not_configured_fails_with_code(contact, settings, caplog):
    from apps.whatsapp import graph as module

    module.reset_fake()
    settings.WHATSAPP_ACCESS_TOKEN = ""
    rows = outbound.queue_text(contact, "Habari", trigger=Out.Trigger.ASSISTANT)
    with caplog.at_level("ERROR"):
        assert outbound.deliver_batch(rows[0].batch) == "done"
    row = Out.objects.get(pk=rows[0].pk)
    assert row.status == Out.Status.FAILED and row.error_code == "not_configured"
    assert any("not configured" in r.getMessage().lower() for r in caplog.records)


def test_product_media_upload_is_cached(make_product, graph, png_bytes):
    product = make_product(name="Red Sneakers")
    image = ProductImage.objects.create(product=product, image=ContentFile(png_bytes(), name="red.png"))

    first = outbound.product_media_id(image)
    second = outbound.product_media_id(image)
    assert first == second == "media.FAKE1"
    assert len(graph.uploads) == 1
    assert graph.uploads[0][1] == "image/png"

    WhatsAppMediaUpload.objects.filter(pk=image.pk).update(uploaded_at=timezone.now() - timedelta(days=26))
    assert outbound.product_media_id(image) == "media.FAKE2"
    assert len(graph.uploads) == 2
