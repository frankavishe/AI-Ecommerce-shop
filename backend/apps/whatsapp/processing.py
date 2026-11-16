"""The inbound pipeline for one stored message (contracts/webhook.md "Processing pipeline").

`process()` runs inside drain_contact, which holds the number's advisory lock, so messages of one
number are handled one at a time and in send order. Nothing here runs inside a long transaction:
the 003 tools commit on their own, and each reply batch is queued in a small atomic block.
"""

import io
import logging
import uuid
from dataclasses import dataclass, field
from datetime import timedelta

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from PIL import Image

from apps.ai import agent, clients, prompts
from apps.ai.models import Conversation
from apps.catalog.models import Product
from apps.orders.models import Cart, Order

from . import graph, outbound, texts
from .models import WINDOW, WhatsAppContact, WhatsAppInboundMessage as Inbound, WhatsAppOutboundMessage as Out

logger = logging.getLogger(__name__)

S = Inbound.Status
T = Out.Trigger


@dataclass
class Job:
    contact: WhatsAppContact
    inbound: Inbound
    conversation: Conversation | None = None
    notes: list = field(default_factory=list)  # server texts sent before the reply (e.g. cart pruned)

    @property
    def lang(self):
        if self.conversation is not None:
            return self.conversation.language
        return self.contact.language


# --- Entry point ---------------------------------------------------------------------------------


def process(inbound):
    contact = WhatsAppContact.objects.get(pk=inbound.contact_id)
    Inbound.objects.filter(pk=inbound.pk).update(status=S.PROCESSING)
    job = Job(contact=contact, inbound=inbound)
    try:
        status, error = _process(job)
    except Exception:
        logger.exception("WhatsApp message %s failed.", inbound.wa_message_id)
        status, error = S.FAILED, "internal_error"
        send_system(job, prompts.fallback("model_unavailable", job.lang))
    inbound.status, inbound.processed_at = status, timezone.now()
    inbound.error = (error or inbound.error or "")[:64]
    inbound.save(update_fields=["status", "error", "processed_at", "chat_message"])
    return status


def _process(job):
    contact, inbound = job.contact, job.inbound
    now = timezone.now()
    previous = contact.last_inbound_at
    if previous is None or inbound.sent_at > previous:  # only forward: a late old message keeps it
        contact.last_inbound_at = inbound.sent_at
        contact.save(update_fields=["last_inbound_at", "updated_at"])

    if now - inbound.sent_at >= WINDOW:  # too old to answer (the window closed long ago)
        job.conversation = existing_conversation(contact)
        record(job)
        return S.RECORDED, "too_old"

    if rate_limited(job):
        return S.RATE_LIMITED, ""

    job.conversation, pruned = current_conversation(contact, previous)
    if pruned:
        job.notes.append(texts.text("cart_pruned", job.lang, names=", ".join(pruned)))

    for handler in CONTROL_HANDLERS:
        result = handler(job)
        if result is not None:
            return result

    if job.conversation.state == Conversation.State.NEEDS_HUMAN:
        return record_for_staff(job)

    return TYPE_HANDLERS.get(inbound.type, handle_unsupported)(job)


# --- Conversation (FR-007, FR-007a, research R12) -------------------------------------------------


def _new_conversation(contact, cart=None):
    conversation = Conversation(channel=Conversation.Channel.WHATSAPP, user=contact.user,
                                language=contact.language)
    if contact.user is None:
        conversation.cart = cart or Cart.objects.create()
    conversation.save()
    contact.conversation = conversation
    contact.save(update_fields=["conversation", "updated_at"])
    return conversation


def existing_conversation(contact):
    return contact.conversation or _new_conversation(contact)


def prune_cart(cart):
    """Drop lines that can no longer be bought. Returns the removed product names."""
    removed = []
    for item in cart.items.select_related("product").order_by("id"):
        product = item.product
        if not product.is_active or product.stock < item.quantity:
            removed.append(product.name)
            item.delete()
    return removed


def current_conversation(contact, previous_inbound_at):
    """The number's conversation, replaced by a fresh one after WHATSAPP_RESET_DAYS of silence
    (never while staff have it) or when the old one was purged. Returns (conversation, removed)."""
    conversation = contact.conversation
    silent = (previous_inbound_at is not None
              and timezone.now() - previous_inbound_at >= timedelta(days=settings.WHATSAPP_RESET_DAYS))
    if conversation is not None and (not silent or conversation.state == Conversation.State.NEEDS_HUMAN):
        return conversation, []
    old_cart = conversation.cart if conversation is not None else None
    new = _new_conversation(contact, cart=old_cart)
    if conversation is None:
        return new, []
    cart = new.cart if contact.user is None else Cart.objects.filter(user=contact.user).first()
    return new, prune_cart(cart) if cart is not None else []


def phone_orders(contact):
    return Order.objects.filter(whatsapp__contact=contact)


# --- Rate limits (FR-019, research R11) -----------------------------------------------------------


def rate_limited(job):
    contact = job.contact
    now = timezone.now()
    recent = Inbound.objects.filter(contact=contact)
    if recent.filter(received_at__gte=now - timedelta(minutes=1)).count() > settings.WHATSAPP_RATE_PER_MINUTE:
        window = timedelta(minutes=1)
    elif recent.filter(received_at__gte=now - timedelta(days=1)).count() > settings.WHATSAPP_RATE_PER_DAY:
        window = timedelta(days=1)
    else:
        return False
    job.conversation = existing_conversation(contact)
    record(job)
    if contact.slowdown_notice_at is None or contact.slowdown_notice_at < now - window:
        contact.slowdown_notice_at = now
        contact.save(update_fields=["slowdown_notice_at", "updated_at"])
        send_system(job, texts.text("slow_down", job.lang))
    return True


# --- Running a turn -------------------------------------------------------------------------------


def meta(job, **extra):
    return {"whatsapp": {"type": job.inbound.type, "wa_message_id": job.inbound.wa_message_id, **extra}}


def record(job, text=None, image=None, **meta_extra):
    """Save the shopper's message to the conversation without answering it."""
    reply = agent.handle_message(job.conversation, text=job.inbound.text if text is None else text,
                                 image=image, user=job.contact.user, meta=meta(job, **meta_extra),
                                 record_only=True)
    job.inbound.chat_message = reply.incoming
    return reply


def run_turn(job, text, image=None, language=None, prefix="", **meta_extra):
    """Run the 003 assistant on one message and send its reply. Returns (status, error)."""
    contact, conversation = job.contact, job.conversation
    reply = agent.handle_message(
        conversation, text=text, image=image, user=contact.user, language=language,
        verified_phone=contact.phone, phone_orders=phone_orders(contact), meta=meta(job, **meta_extra),
    )
    job.inbound.chat_message = reply.incoming
    conversation.refresh_from_db()
    for hook in AFTER_TURN:
        hook(job, reply)
    send_reply(job, reply, prefix)
    if contact.language != conversation.language:
        contact.language = conversation.language
        contact.save(update_fields=["language", "updated_at"])
    return (S.FAILED, reply.error) if reply.error else (S.ANSWERED, "")


def product_photos(reply_text, products):
    """(media_id, caption) for up to WHATSAPP_MAX_PRODUCT_PHOTOS products shown in the reply:
    the ones named in the text first, then the rest in the order the tools returned them (R7).
    Names and prices come from the database."""
    lowered = (reply_text or "").lower()
    named = [card for card in products if card["name"].lower() in lowered]
    ordered = named + [card for card in products if card not in named]
    photos = []
    for card in ordered:
        if len(photos) >= settings.WHATSAPP_MAX_PRODUCT_PHOTOS:
            break
        product = Product.objects.filter(pk=card["id"], is_active=True).prefetch_related("images").first()
        image = next(iter(product.images.all()), None) if product else None
        if image is None:
            continue
        try:
            media_id = outbound.product_media_id(image)
        except (graph.GraphError, graph.NotConfigured) as exc:
            logger.warning("Product photo %s not uploaded to WhatsApp: %s", image.pk, exc)
            continue
        photos.append((media_id, f"{product.name} — {texts.format_tzs(product.price)} TZS"))
    return photos


def send_reply(job, reply, prefix=""):
    """Queue the reply as one ordered batch: notes, text chunks, product photos, then any extras
    (payment message, Confirm buttons) added by REPLY_EXTRAS."""
    contact, conversation = job.contact, job.conversation
    body = "\n\n".join(part for part in (prefix, reply.text) if part)
    photos = product_photos(reply.text, reply.payload.get("products") or [])
    try:
        with transaction.atomic():
            batch = uuid.uuid4()
            for note in job.notes:
                outbound.queue_text(contact, note, T.SYSTEM, conversation, batch=batch)
            if body:
                outbound.queue_text(contact, body, T.ASSISTANT, conversation, batch=batch)
            for media_id, caption in photos:
                outbound.queue_image(contact, media_id, caption, T.ASSISTANT, conversation, batch=batch)
            for extra in REPLY_EXTRAS:
                extra(job, reply, batch)
            outbound.flush(batch)
    except outbound.WindowClosed:
        # only a delayed message can get here: the reply is stored, but WhatsApp would refuse it
        logger.warning("WhatsApp window closed for %s; reply to %s not sent.", contact.phone,
                       job.inbound.wa_message_id)
        job.inbound.error = "window_closed"


def send_system(job, text):
    """A server text outside a turn (slow-down note, fixed replies). Never raises."""
    try:
        with transaction.atomic():
            rows = outbound.queue_text(job.contact, text, T.SYSTEM, job.conversation)
            if rows:
                outbound.flush(rows[0].batch)
    except outbound.WindowClosed:
        logger.warning("WhatsApp window closed for %s; system text not sent.", job.contact.phone)


def reply_fixed(job, key, status, error=""):
    """Record the message and answer with a fixed server text."""
    record(job)
    send_system(job, texts.text(key, job.lang))
    return status, error


# --- Handlers by type ----------------------------------------------------------------------------


def handle_text(job):
    return run_turn(job, job.inbound.text)


def handle_unsupported(job):
    return reply_fixed(job, "unsupported", S.REJECTED)


# --- Media (research R7, R9) ----------------------------------------------------------------------


class MediaRejected(Exception):
    """The file is not one we accept; `key` is the server text to answer with."""

    def __init__(self, key):
        super().__init__(key)
        self.key = key


class MediaFailed(Exception):
    """The file could not be fetched from WhatsApp; the shopper is asked to send it again."""


IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp"}
IMAGE_FORMATS = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}
AUDIO_EXTENSIONS = {"audio/ogg": "ogg", "audio/mpeg": "mp3", "audio/mp4": "m4a", "audio/aac": "aac",
                    "audio/amr": "amr", "audio/opus": "opus", "audio/wav": "wav"}


def _base_mime(mime):
    return (mime or "").split(";", 1)[0].strip().lower()


def download_media(job, max_bytes, allowed, rejected_key):
    """Fetch the message's media (a fresh URL each time, it expires after ~5 min). `allowed` is a
    predicate on the base mime type. Returns (bytes, base mime)."""
    inbound = job.inbound
    mime = _base_mime(inbound.media_mime)
    if not allowed(mime):
        raise MediaRejected(rejected_key)
    try:
        client = graph.get_client()
        info = client.get_media(inbound.media_id)
        if (info.get("file_size") or 0) > max_bytes:
            raise MediaRejected(rejected_key)
        mime = _base_mime(info.get("mime_type")) or mime
        if not allowed(mime):
            raise MediaRejected(rejected_key)
        content = client.download(info["url"])
    except (graph.GraphError, graph.NotConfigured, KeyError) as exc:
        logger.warning("WhatsApp media %s not downloaded: %s", inbound.media_id, exc)
        raise MediaFailed from exc
    if len(content) > max_bytes:
        raise MediaRejected(rejected_key)
    return content, mime


def _media_reply(job, exc):
    if isinstance(exc, MediaFailed):
        return reply_fixed(job, "media_retry", S.FAILED, "media_retry")
    return reply_fixed(job, exc.key, S.REJECTED, exc.key)


def fetch_image(job):
    """The photo as a ContentFile, or MediaRejected/MediaFailed."""
    content, _ = download_media(job, settings.AI_UPLOAD_MAX_BYTES, IMAGE_MIMES.__contains__, "image_rejected")
    try:  # trust the bytes, not the declared type (a GIF sent as image/jpeg is still a GIF)
        fmt = Image.open(io.BytesIO(content)).format
    except (OSError, ValueError):
        fmt = None
    if fmt not in IMAGE_FORMATS:
        raise MediaRejected("image_rejected")
    return ContentFile(content, name=f"wa-{job.inbound.pk}.{IMAGE_FORMATS[fmt]}")


def handle_image(job):
    try:
        image = fetch_image(job)
    except (MediaRejected, MediaFailed) as exc:
        return _media_reply(job, exc)
    return run_turn(job, job.inbound.text, image=image)


def fetch_voice(job):
    """Download, store and transcribe the voice note. Returns the transcript (possibly empty) and
    its language; raises MediaRejected/MediaFailed or clients.ModelUnavailable."""
    inbound = job.inbound
    content, mime = download_media(job, settings.WHATSAPP_VOICE_MAX_BYTES,
                                   lambda m: m.startswith("audio/"), "voice_retry")
    filename = f"wa-{inbound.pk}.{AUDIO_EXTENSIONS.get(mime, 'ogg')}"
    inbound.media.save(filename, ContentFile(content), save=False)
    inbound.save(update_fields=["media"])
    heard = clients.transcribe(content, filename)
    transcript = " ".join((heard.get("text") or "").split())
    inbound.transcript, inbound.transcript_language = transcript, heard.get("language") or ""
    inbound.duration_s = heard.get("duration")
    inbound.save(update_fields=["transcript", "transcript_language", "duration_s"])
    return transcript, heard.get("language")


def handle_audio(job):
    try:
        transcript, language = fetch_voice(job)
    except (MediaRejected, MediaFailed) as exc:
        return _media_reply(job, exc)
    except clients.ModelUnavailable as exc:
        logger.warning("Speech model unavailable: %s", exc)
        record(job, text="")
        send_system(job, prompts.fallback("model_unavailable", job.lang))
        return S.FAILED, "speech_unavailable"

    if not transcript or (job.inbound.duration_s or 0) > settings.WHATSAPP_VOICE_MAX_SECONDS:
        return reply_fixed(job, "voice_retry", S.REJECTED, "voice_retry")
    prefix = texts.heard(transcript, language or job.lang)
    return run_turn(job, transcript, language=language, prefix=prefix, transcript=transcript)


def record_for_staff(job):
    """A conversation handed to staff: save the message, with the photo or the voice transcript so
    staff can read it, and send nothing (US4-1). Media problems are logged, never answered."""
    inbound = job.inbound
    try:
        if inbound.type == Inbound.Type.IMAGE:
            record(job, image=fetch_image(job))
            return S.RECORDED, ""
        if inbound.type == Inbound.Type.AUDIO:
            transcript, _ = fetch_voice(job)
            record(job, text=transcript, transcript=transcript)
            return S.RECORDED, ""
    except (MediaRejected, MediaFailed, clients.ModelUnavailable) as exc:
        logger.warning("WhatsApp %s %s kept without its media: %r", inbound.type, inbound.wa_message_id, exc)
    record(job)
    return S.RECORDED, ""


# --- Order-update opt-out (FR-021, research R14) ---------------------------------------------------

STOP_WORDS = {"stop", "acha", "sitaki", "unsubscribe"}
START_WORDS = {"start", "anza"}


def updates_control(job):
    """CONTROL_HANDLERS step: a text that is exactly STOP/acha/... or START/anza switches order
    updates and is answered by the server, never by the assistant."""
    if job.inbound.type != Inbound.Type.TEXT:
        return None
    word = (job.inbound.text or "").strip().lower()
    if word not in STOP_WORDS | START_WORDS:
        return None
    allowed = word in START_WORDS
    if job.contact.updates_allowed != allowed:
        job.contact.updates_allowed = allowed
        job.contact.save(update_fields=["updates_allowed", "updated_at"])
    return reply_fixed(job, "started" if allowed else "stopped", S.ANSWERED)


TYPE_HANDLERS = {
    Inbound.Type.TEXT: handle_text,
    Inbound.Type.IMAGE: handle_image,
    Inbound.Type.AUDIO: handle_audio,
    Inbound.Type.UNSUPPORTED: handle_unsupported,
}

# Extension points: control words (before the assistant), after-turn bookkeeping, reply extras.
CONTROL_HANDLERS = [updates_control]
AFTER_TURN = []
REPLY_EXTRAS = []

# Registered last: these modules import this one, so look their functions up at call time.
from . import checkout_buttons, linking  # noqa: E402

TYPE_HANDLERS[Inbound.Type.BUTTON] = lambda job: checkout_buttons.handle_button(job)
CONTROL_HANDLERS.append(lambda job: linking.control(job))
AFTER_TURN.append(lambda job, reply: checkout_buttons.after_turn(job, reply))
REPLY_EXTRAS.append(lambda job, reply, batch: checkout_buttons.reply_extras(job, reply, batch))
