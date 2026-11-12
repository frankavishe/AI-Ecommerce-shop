import json
from unittest import mock

import pytest

from apps.ai.models import Conversation
from apps.whatsapp import testing as wa
from apps.whatsapp.models import (
    WhatsAppContact, WhatsAppInboundMessage as Inbound, WhatsAppOutboundMessage as Out,
)

pytestmark = pytest.mark.django_db

URL = "/api/whatsapp/webhook/"


# --- GET handshake --------------------------------------------------------------------------------


def handshake(client, mode="subscribe", token="test-verify", challenge="1158201444"):
    return client.get(URL, {"hub.mode": mode, "hub.verify_token": token, "hub.challenge": challenge})


def test_handshake_ok_returns_challenge_as_plain_text(client):
    response = handshake(client)
    assert response.status_code == 200
    assert response.content == b"1158201444"
    assert response["Content-Type"].startswith("text/plain")


@pytest.mark.parametrize("kwargs", [{"token": "wrong"}, {"mode": "unsubscribe"}, {"token": ""}])
def test_handshake_rejected(client, kwargs):
    assert handshake(client, **kwargs).status_code == 403


def test_handshake_rejected_when_no_token_configured(client, settings):
    settings.WHATSAPP_VERIFY_TOKEN = ""
    assert handshake(client, token="").status_code == 403


# --- POST signature -------------------------------------------------------------------------------


@pytest.mark.parametrize("header", [None, "sha256=bad", "garbage"])
def test_bad_or_missing_signature_is_403_and_stores_nothing(client, header, chat_model):
    raw = json.dumps(wa.text_message("habari")).encode()
    extra = {} if header is None else {"HTTP_X_HUB_SIGNATURE_256": header}
    with mock.patch("apps.whatsapp.tasks.drain_contact.delay") as delay:
        response = client.post(URL, data=raw, content_type="application/json", **extra)
    assert response.status_code == 403
    assert not WhatsAppContact.objects.exists()
    assert not Inbound.objects.exists()
    delay.assert_not_called()
    assert chat_model.requests == []


def test_wrong_secret_is_403(client):
    response = wa.signed_post(client, wa.text_message("habari"), secret="other-secret")
    assert response.status_code == 403
    assert not Inbound.objects.exists()


# --- POST messages --------------------------------------------------------------------------------


def test_valid_text_creates_contact_and_inbound(deliver_inbound, chat_model, graph):
    chat_model.add("Karibu!")
    response = deliver_inbound(wa.text_message("habari", wa_id="255742000331", name="Asha"))
    assert response.status_code == 200
    assert response.json() == {"ok": True}

    contact = WhatsAppContact.objects.get()
    assert contact.wa_id == "255742000331"
    assert contact.phone == "+255742000331"
    assert contact.profile_name == "Asha"
    inbound = Inbound.objects.get()
    assert inbound.type == "text" and inbound.text == "habari"
    assert inbound.status == "answered"
    assert graph.texts == ["Karibu!"]


def test_same_payload_five_times_is_processed_once(deliver_inbound, chat_model, graph):
    payload = wa.text_message("habari", message_id="wamid.SAME")
    for _ in range(5):
        assert deliver_inbound(payload).status_code == 200
    assert Inbound.objects.count() == 1
    assert len(chat_model.requests) == 1
    assert len(graph.texts) == 1


def test_other_phone_number_id_is_ignored(deliver_inbound, chat_model):
    response = deliver_inbound(wa.text_message("habari", phone_number_id="someone-else"))
    assert response.status_code == 200
    assert not Inbound.objects.exists()
    assert chat_model.requests == []


@pytest.mark.parametrize("body", [{"object": "page", "entry": []}, {"hello": 1}, [1, 2]])
def test_non_waba_json_is_ignored(deliver_inbound, body):
    assert deliver_inbound(body).status_code == 200
    assert not Inbound.objects.exists()


def test_invalid_json_is_ignored(client):
    raw = b"not json"
    response = client.post(URL, data=raw, content_type="application/json",
                           HTTP_X_HUB_SIGNATURE_256=wa.sign(raw))
    assert response.status_code == 200


def test_webhook_makes_no_network_calls_in_the_request(client, graph, chat_model):
    with mock.patch("apps.whatsapp.tasks.drain_contact.delay") as delay:
        response = wa.signed_post(client, wa.text_message("habari"))
    assert response.status_code == 200
    assert graph.sent == [] and chat_model.requests == []
    assert Inbound.objects.get().status == "received"
    assert not Conversation.objects.exists()
    _ = delay  # queued on commit, which a test transaction never reaches


# --- POST statuses --------------------------------------------------------------------------------


@pytest.fixture
def sent_row(contact_factory):
    contact = contact_factory()
    return Out.objects.create(contact=contact, kind="text", trigger="assistant", body={}, text="hi",
                              wa_message_id="wamid.OUT1", status=Out.Status.SENT)


def test_status_moves_forward_only(deliver_inbound, sent_row):
    deliver_inbound(wa.status_update("wamid.OUT1", "read"))
    sent_row.refresh_from_db()
    assert sent_row.status == "read"
    deliver_inbound(wa.status_update("wamid.OUT1", "delivered"))
    sent_row.refresh_from_db()
    assert sent_row.status == "read"


def test_failed_status_stores_error(deliver_inbound, sent_row):
    deliver_inbound(wa.status_update("wamid.OUT1", "failed",
                                     error={"code": 131047, "title": "Re-engagement message"}))
    sent_row.refresh_from_db()
    assert sent_row.status == "failed"
    assert sent_row.error_code == "131047"
    assert sent_row.error == "Re-engagement message"
    deliver_inbound(wa.status_update("wamid.OUT1", "read"))
    sent_row.refresh_from_db()
    assert sent_row.status == "failed"


def test_unknown_status_id_is_ignored(deliver_inbound, sent_row):
    assert deliver_inbound(wa.status_update("wamid.UNKNOWN", "read")).status_code == 200
    sent_row.refresh_from_db()
    assert sent_row.status == "sent"
