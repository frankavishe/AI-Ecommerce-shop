"""US3: photos and voice notes from WhatsApp (T040, research R7/R9)."""

import os
from datetime import timedelta

import pytest
from django.core.files.base import ContentFile
from django.utils import timezone

from apps.ai import indexing
from apps.ai.clients import ModelUnavailable
from apps.ai.models import ChatMessage
from apps.ai.tasks import purge_old_conversations
from apps.ai.testing import tool_call
from apps.catalog.models import ProductImage
from apps.whatsapp import testing as wa
from apps.whatsapp.models import WhatsAppContact, WhatsAppInboundMessage as Inbound

pytestmark = pytest.mark.django_db

RED, BLUE = (230, 20, 20), (20, 40, 220)
OGG = b"OggS" + b"\x00" * 200


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    return tmp_path


@pytest.fixture
def photo_catalog(shoe_catalog, png_bytes):
    for product, colour in ((shoe_catalog.red, RED), (shoe_catalog.blue, BLUE)):
        image = ProductImage(product=product)
        image.image.save("p.png", ContentFile(png_bytes(colour)), save=True)
        indexing.index_product_image(image.pk)
    return shoe_catalog


def inbound(message_id):
    return Inbound.objects.get(wa_message_id=message_id)


# --- Photos ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("caption", ["", "nina hizi kwa size 42?"])
def test_photo_runs_image_search(deliver_inbound, chat_model, graph, photo_catalog, png_bytes, caption):
    graph.add_media("MEDIA_RED", png_bytes(RED), "image/jpeg")
    chat_model.add([tool_call("search_by_image")], "Hizi ni Red Sneakers kwa 45,000 TZS.")
    deliver_inbound(wa.image_message("MEDIA_RED", caption=caption, message_id="wamid.P1"))

    row = inbound("wamid.P1")
    assert row.status == "answered"
    assert row.chat_message.image  # the 003 photo storage (and its 30-day purge) apply
    prompt = chat_model.requests[0]["messages"][-1]["content"]
    assert prompt.startswith(caption) and "attached a photo" in prompt
    reply = row.contact.conversation.messages.filter(role="assistant").last()
    assert reply.payload["products"][0]["name"] == "Red Sneakers"
    assert graph.texts == ["Hizi ni Red Sneakers kwa 45,000 TZS."]


@pytest.mark.parametrize("setup", ["file_size", "bytes", "gif", "gif_as_jpeg"])
def test_bad_photos_are_rejected_without_the_model(deliver_inbound, chat_model, graph, png_bytes, settings, setup):
    content, mime, size = png_bytes(RED), "image/jpeg", None
    if setup == "file_size":
        size = settings.AI_UPLOAD_MAX_BYTES + 1
    elif setup == "bytes":
        settings.AI_UPLOAD_MAX_BYTES = len(content) - 1
    elif setup == "gif":
        content, mime = png_bytes(RED, fmt="GIF"), "image/gif"
    else:
        content = png_bytes(RED, fmt="GIF")  # says jpeg, isn't
    graph.add_media("M", content, mime, file_size=size)
    deliver_inbound(wa.image_message("M", mime=mime, message_id="wamid.BAD"))

    assert chat_model.requests == []
    assert graph.texts == ["Tafadhali tuma picha ya JPEG, PNG au WebP isiyozidi MB 10."]
    row = inbound("wamid.BAD")
    assert row.status == "rejected" and row.error == "image_rejected"


def test_media_download_failure_asks_to_resend(deliver_inbound, chat_model, graph, png_bytes):
    graph.add_media("M", png_bytes(RED))
    graph.download_fails = True
    deliver_inbound(wa.image_message("M", message_id="wamid.DL"))
    assert chat_model.requests == []
    assert graph.texts == ["Samahani, sikuweza kupakua faili. Tafadhali itume tena."]
    assert inbound("wamid.DL").error == "media_retry"

    deliver_inbound(wa.image_message("UNKNOWN", message_id="wamid.DL2"))  # media id Meta doesn't know
    assert inbound("wamid.DL2").error == "media_retry"


# --- Voice notes ----------------------------------------------------------------------------------


def test_voice_note_is_transcribed_and_answered(deliver_inbound, chat_model, graph, speech):
    speech.add({"text": "mna simu za Samsung?", "language": "swahili", "duration": 3.4})
    graph.add_media("VOICE", OGG, "audio/ogg; codecs=opus")
    chat_model.add("Ndiyo, tuna simu za Samsung.")
    deliver_inbound(wa.audio_message("VOICE", message_id="wamid.V1"))

    assert speech.calls[0][0] == OGG and speech.calls[0][1].endswith(".ogg")
    assert chat_model.last_messages[-1]["content"] == "mna simu za Samsung?"
    assert graph.texts == ['🎤 Nimesikia: "mna simu za Samsung?"\n\nNdiyo, tuna simu za Samsung.']
    row = inbound("wamid.V1")
    assert row.status == "answered"
    assert (row.transcript, row.transcript_language, row.duration_s) == ("mna simu za Samsung?", "sw", 3.4)
    assert row.media and os.path.exists(row.media.path)
    assert row.chat_message.payload["whatsapp"]["transcript"] == "mna simu za Samsung?"
    assert row.contact.conversation.language == "sw"


def test_english_voice_note_switches_language(deliver_inbound, chat_model, graph, speech):
    speech.add({"text": "do you have phones?", "language": "english", "duration": 2})
    graph.add_media("VOICE", OGG, "audio/ogg")
    chat_model.add("Yes, we do.")
    deliver_inbound(wa.audio_message("VOICE"))
    assert graph.texts == ['🎤 I heard: "do you have phones?"\n\nYes, we do.']
    assert WhatsAppContact.objects.get().language == "en"


@pytest.mark.parametrize("case", ["long", "big", "empty"])
def test_unusable_voice_notes_ask_to_type(deliver_inbound, chat_model, graph, speech, settings, case):
    if case == "long":
        speech.add({"text": "habari", "language": "sw", "duration": settings.WHATSAPP_VOICE_MAX_SECONDS + 1})
    elif case == "empty":
        speech.add({"text": "  ", "language": "sw", "duration": 2})
    graph.add_media("VOICE", OGG, "audio/ogg",
                    file_size=settings.WHATSAPP_VOICE_MAX_BYTES + 1 if case == "big" else None)
    deliver_inbound(wa.audio_message("VOICE", message_id="wamid.VX"))

    assert chat_model.requests == []
    assert graph.texts[-1].startswith("Samahani, sikuweza kusikia vizuri.")
    assert inbound("wamid.VX").error == "voice_retry"
    if case == "big":
        assert speech.calls == []


def test_speech_down_sends_the_fallback(deliver_inbound, chat_model, graph, speech):
    speech.add(ModelUnavailable("whisper down"))
    graph.add_media("VOICE", OGG, "audio/ogg")
    deliver_inbound(wa.audio_message("VOICE", message_id="wamid.SD"))

    assert chat_model.requests == []
    assert len(graph.texts) == 1
    row = inbound("wamid.SD")
    assert row.status == "failed" and row.error == "speech_unavailable"
    assert row.contact.conversation.messages.filter(role="user").exists()  # still saved for staff


@pytest.mark.parametrize("kind", ["video", "document", "sticker", "location", "contacts"])
def test_unsupported_types(deliver_inbound, chat_model, graph, kind):
    deliver_inbound(wa.unsupported_message(kind, message_id=f"wamid.{kind}"))
    assert chat_model.requests == []
    assert graph.texts == ["Ninaweza kusoma ujumbe wa maandishi, picha na sauti tu."]
    assert inbound(f"wamid.{kind}").status == "rejected"


# --- Retention ------------------------------------------------------------------------------------


def test_purge_deletes_old_voice_audio(contact_factory):
    contact = contact_factory()
    old = Inbound.objects.create(wa_message_id="wamid.OLD", contact=contact, type="audio",
                                 sent_at=timezone.now())
    old.media.save("old.ogg", ContentFile(OGG), save=True)
    new = Inbound.objects.create(wa_message_id="wamid.NEW", contact=contact, type="audio",
                                 sent_at=timezone.now())
    new.media.save("new.ogg", ContentFile(OGG), save=True)
    path = old.media.path
    Inbound.objects.filter(pk=old.pk).update(received_at=timezone.now() - timedelta(days=31))

    assert purge_old_conversations()["audio"] == 1

    old.refresh_from_db()
    new.refresh_from_db()
    assert not old.media and not os.path.exists(path)
    assert new.media
    assert ChatMessage.objects.count() == 0
