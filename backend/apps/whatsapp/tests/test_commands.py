"""whatsapp_simulate and whatsapp_voice_eval (T056, T057, T061)."""

import json
from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from apps.ai.testing import tool_call
from apps.whatsapp.models import WhatsAppInboundMessage as Inbound

pytestmark = pytest.mark.django_db


@pytest.fixture
def debug(settings, tmp_path):
    settings.DEBUG = True
    settings.MEDIA_ROOT = tmp_path
    return settings


def simulate(*args, capture=None):
    out = StringIO()
    if capture is None:
        call_command("whatsapp_simulate", "--inline", *args, stdout=out)
    else:
        with capture(execute=True):
            call_command("whatsapp_simulate", "--inline", *args, stdout=out)
    return out.getvalue()


def test_refuses_without_debug(settings):
    settings.DEBUG = False
    with pytest.raises(CommandError, match="DEBUG"):
        call_command("whatsapp_simulate", "--text", "habari")


def test_text_goes_through_the_webhook(debug, chat_model, graph, django_capture_on_commit_callbacks):
    chat_model.add("Karibu dukani!")
    output = simulate("--from", "255742000999", "--name", "Juma", "--text", "habari",
                      capture=django_capture_on_commit_callbacks)
    assert "HTTP 200" in output
    inbound = Inbound.objects.get()
    assert (inbound.contact.wa_id, inbound.contact.profile_name, inbound.text) == ("255742000999", "Juma", "habari")
    assert graph.texts == ["Karibu dukani!"]


def test_image_is_served_from_the_staged_file(debug, chat_model, graph, png_bytes, tmp_path,
                                              django_capture_on_commit_callbacks):
    photo = tmp_path / "shoe.png"
    photo.write_bytes(png_bytes((200, 0, 0)))
    simulate("--image", str(photo), "--caption", "mna hii?", capture=django_capture_on_commit_callbacks)
    inbound = Inbound.objects.get()
    assert inbound.type == "image" and inbound.media_id.startswith("sim.")
    assert inbound.status == "answered"
    assert inbound.chat_message.image  # the bytes reached the assistant


def test_logging_graph_serves_staged_media(debug):
    from apps.whatsapp import graph as module

    staged = module.sim_media_dir() / "abc.ogg"
    staged.parent.mkdir(parents=True)
    staged.write_bytes(b"OggS-123")
    fake = module.LoggingGraph()
    info = fake.get_media("sim.abc.ogg")
    assert info["mime_type"] == "audio/ogg" and info["file_size"] == 8
    assert fake.download(info["url"]) == b"OggS-123"
    assert fake.get_media("sim.../../secret")["file_size"] == 0


def test_bad_secret_is_reported(debug):
    debug.WHATSAPP_APP_SECRET = "test-secret"
    from apps.whatsapp import testing

    original = testing.sign
    testing.sign = lambda raw, secret=None: original(raw, "wrong")
    try:
        with pytest.raises(CommandError, match="refused"):
            simulate("--text", "habari")
    finally:
        testing.sign = original


def test_timing_reports_when_no_reply(debug):
    output = simulate("--text", "habari", "--timing", "--wait", "0.2")  # on-commit work never runs here
    assert "No reply queued" in output


@pytest.fixture
def voice_cases(tmp_path):
    (tmp_path / "a.ogg").write_bytes(b"OggS-a")
    (tmp_path / "b.ogg").write_bytes(b"OggS-b")
    (tmp_path / "cases.json").write_text(json.dumps([
        {"file": "a.ogg", "language": "sw", "expect_product": "Red Sneakers"},
        {"file": "b.ogg", "language": "en", "expect_product": "Red Sneakers"},
    ]), encoding="utf-8")
    return tmp_path


def test_voice_eval_scores_per_language(voice_cases, speech, chat_model, shoe_catalog):
    speech.add({"text": "nataka viatu vyekundu", "language": "sw", "duration": 2.0},
               {"text": "do you have phones", "language": "en", "duration": 2.0})
    chat_model.add([tool_call("search_products", query="viatu vyekundu")], "Tuna Red Sneakers.",
                   "We have chargers only.")
    out = StringIO()
    with pytest.raises(CommandError, match="below"):
        call_command("whatsapp_voice_eval", "--dir", str(voice_cases), "--min", "0.8", stdout=out)
    text = out.getvalue()
    assert "sw: 1/1 = 100%" in text and "en: 0/1 = 0%" in text and "all: 1/2 = 50%" in text


def test_voice_eval_needs_cases(tmp_path):
    with pytest.raises(CommandError, match="cases.json"):
        call_command("whatsapp_voice_eval", "--dir", str(tmp_path))


def test_logging_graph_ids_are_unique_across_instances(debug, contact_factory):
    """A restarted dev server must not reuse wamids already stored (wa_message_id is unique)."""
    from apps.whatsapp import graph as module

    first, second = module.LoggingGraph(), module.LoggingGraph()
    body = {"to": "255742000331", "type": "text", "text": {"body": "hi"}}
    assert first.send(body) != second.send(body)
    assert first.upload_media(b"x", "image/png") != second.upload_media(b"x", "image/png")
