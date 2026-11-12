"""Outbound WhatsApp messages (research R10, R15; contracts/outbound.md).

Callers queue rows (`queue_*`) inside their transaction and then `flush(batch)`: the rows of one
batch are delivered in `position` order by the `deliver` task once the transaction commits. Only
templates may go out when the 24-hour window is closed.
"""

import logging
import mimetypes
import re
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import graph
from .models import WhatsAppMediaUpload, WhatsAppOrderNotification, WhatsAppOutboundMessage as Out

logger = logging.getLogger(__name__)

MEDIA_REUSE = timedelta(days=25)
CAPTION_LIMIT = 1024
BUTTON_BODY_LIMIT = 1024
BUTTON_TITLE_LIMIT = 20


class WindowClosed(Exception):
    """The shopper's last message is 24 hours old or more: only templates may be sent."""


# --- Splitting (R15) -----------------------------------------------------------------------------

_NUMBER = re.compile(r"[\d][\d.,]*")
_CURRENCY = {"tzs", "tsh", "tshs", "sh"}
_SEPARATORS = (re.compile(r"\n\s*\n"), re.compile(r"\n"), re.compile(r"(?<=[.?!])\s"), re.compile(r"\s"))


def _is_number(token):
    return bool(_NUMBER.fullmatch(token.strip(".,;:!?)(")))


def _is_currency(token):
    return token.strip(".,;:!?)(").lower() in _CURRENCY


def _splittable(text, position):
    """A split here would not separate an amount from its currency."""
    left, right = text[:position].split(), text[position:].split()
    if not left or not right:
        return False
    a, b = left[-1], right[0]
    return not ((_is_number(a) and _is_currency(b)) or (_is_currency(a) and _is_number(b)))


def _cut(text, limit):
    window = text[: limit + 1]
    for pattern in _SEPARATORS:
        positions = [m.start() for m in pattern.finditer(window) if 0 < m.start() <= limit]
        for position in reversed(positions):
            if _splittable(text, position):
                return position
    return limit  # one token longer than the limit: nothing better to do


def split_text(text, limit=None):
    limit = limit or settings.WHATSAPP_TEXT_LIMIT
    text = (text or "").strip()
    chunks = []
    while len(text) > limit:
        position = _cut(text, limit)
        chunks.append(text[:position].strip())
        text = text[position:].strip()
    if text:
        chunks.append(text)
    return chunks


# --- Queueing ------------------------------------------------------------------------------------


def _envelope(contact):
    return {"messaging_product": "whatsapp", "recipient_type": "individual", "to": contact.wa_id}


def _check_window(contact):
    if not contact.window_open:
        raise WindowClosed(contact.phone)


def _queue(contact, kind, body, text, trigger, conversation=None, staff_user=None, batch=None):
    batch = batch or uuid.uuid4()
    position = Out.objects.filter(batch=batch).count()
    return Out.objects.create(
        contact=contact, conversation=conversation, kind=kind, trigger=trigger,
        body={**_envelope(contact), **body}, text=text, batch=batch, position=position,
        staff_user=staff_user,
    )


def queue_text(contact, text, trigger, conversation=None, staff_user=None, batch=None, limit=None):
    """Queue `text` split into chunks. Returns the rows (all in one batch)."""
    _check_window(contact)
    batch = batch or uuid.uuid4()
    return [
        _queue(contact, Out.Kind.TEXT, {"type": "text", "text": {"body": chunk, "preview_url": True}},
               chunk, trigger, conversation, staff_user, batch)
        for chunk in split_text(text, limit)
    ]


def queue_image(contact, media_id, caption, trigger, conversation=None, staff_user=None, batch=None):
    _check_window(contact)
    caption = (caption or "")[:CAPTION_LIMIT]
    return _queue(contact, Out.Kind.IMAGE, {"type": "image", "image": {"id": media_id, "caption": caption}},
                  caption, trigger, conversation, staff_user, batch)


def queue_buttons(contact, body, buttons, trigger, conversation=None, staff_user=None, batch=None):
    """`buttons`: [(id, title)], at most 3."""
    _check_window(contact)
    body = body[:BUTTON_BODY_LIMIT]
    interactive = {
        "type": "button",
        "body": {"text": body},
        "action": {"buttons": [
            {"type": "reply", "reply": {"id": button_id[:256], "title": title[:BUTTON_TITLE_LIMIT]}}
            for button_id, title in buttons[:3]
        ]},
    }
    text = body + "\n" + " | ".join(title for _, title in buttons[:3])
    return _queue(contact, Out.Kind.BUTTONS, {"type": "interactive", "interactive": interactive},
                  text, trigger, conversation, staff_user, batch)


def queue_template(contact, name, params, trigger, conversation=None, staff_user=None, batch=None, text=""):
    """Approved templates may be sent at any time (no window check)."""
    template = {"name": name, "language": {"code": contact.language or "sw"}}
    if params:
        template["components"] = [{"type": "body", "parameters": [
            {"type": "text", "text": str(value)} for value in params
        ]}]
    return _queue(contact, Out.Kind.TEMPLATE, {"type": "template", "template": template},
                  text or f"[{name}] " + " · ".join(str(p) for p in params), trigger,
                  conversation, staff_user, batch)


def flush(batch):
    """Deliver the batch once the surrounding transaction commits."""
    from .tasks import deliver

    batch = str(batch)
    transaction.on_commit(lambda: deliver.delay(batch))


def product_media_id(product_image):
    """Upload a product photo to WhatsApp once and reuse its media id for 25 days (R7)."""
    fresh = WhatsAppMediaUpload.objects.filter(
        product_image=product_image, uploaded_at__gte=timezone.now() - MEDIA_REUSE
    ).first()
    if fresh is not None:
        return fresh.media_id
    field = product_image.image
    field.open("rb")
    try:
        content = field.read()
    finally:
        field.close()
    mime = mimetypes.guess_type(field.name)[0] or "image/jpeg"
    media_id = graph.get_client().upload_media(content, mime)
    WhatsAppMediaUpload.objects.update_or_create(
        product_image=product_image, defaults={"media_id": media_id, "uploaded_at": timezone.now()},
    )
    return media_id


# --- Delivery (R10) ------------------------------------------------------------------------------

_NOTIFICATION_STATE = {
    Out.Status.SENT: WhatsAppOrderNotification.State.SENT,
    Out.Status.FAILED: WhatsAppOrderNotification.State.FAILED,
    Out.Status.SKIPPED: WhatsAppOrderNotification.State.FAILED,
}


def _finish(row, status, **fields):
    row.status = status
    row.status_at = timezone.now()
    for name, value in fields.items():
        setattr(row, name, value)
    row.save()
    WhatsAppOrderNotification.objects.filter(outbound=row).update(state=_NOTIFICATION_STATE[status])


def _close_rest(rows, status, error_code="", error=""):
    for row in rows:
        _finish(row, status, error_code=error_code, error=error)


def deliver_batch(batch_id, last_attempt=False):
    """Send the batch's queued rows in order. Returns "retry" when a transient error should be
    retried later (the remaining rows stay queued), otherwise "done"."""
    rows = list(Out.objects.filter(batch=batch_id, status=Out.Status.QUEUED).order_by("position", "id"))
    if not rows:
        return "done"
    try:
        client = graph.get_client()
    except graph.NotConfigured as exc:
        logger.error("WhatsApp is not configured (%s); %d message(s) not sent.", exc, len(rows))
        _close_rest(rows, Out.Status.FAILED, "not_configured", str(exc))
        return "done"

    for index, row in enumerate(rows):
        row.attempts += 1
        try:
            wa_message_id = client.send(row.body)
        except graph.GraphError as exc:
            code = str(exc.code) if exc.code is not None else (str(exc.http_status or "network"))
            if exc.transient and not last_attempt:
                row.error_code, row.error = code, exc.title
                row.save(update_fields=["attempts", "error_code", "error"])
                return "retry"
            if exc.code == 190:
                logger.error("WhatsApp token rejected: check WHATSAPP_ACCESS_TOKEN (%s)", exc.title)
            else:
                logger.error("WhatsApp send failed for message %s: %s", row.pk, exc)
            _finish(row, Out.Status.FAILED, error_code=code, error=exc.title)
            if exc.recipient:
                _close_rest(rows[index + 1:], Out.Status.SKIPPED, error=f"batch stopped by {code}")
                return "done"
            if exc.transient:  # last attempt used up: the rest would fail the same way
                _close_rest(rows[index + 1:], Out.Status.FAILED, code, exc.title)
                return "done"
            continue
        _finish(row, Out.Status.SENT, wa_message_id=wa_message_id)
    return "done"
