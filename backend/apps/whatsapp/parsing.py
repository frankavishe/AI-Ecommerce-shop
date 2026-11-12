"""Webhook JSON → plain dataclasses (contracts/webhook.md "Inbound message mapping").

Tolerant of missing keys: anything it cannot read is skipped, never raised.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone as dt_timezone

from django.utils import timezone


@dataclass
class Message:
    wa_id: str
    id: str
    type: str  # text | image | audio | button | unsupported
    raw_type: str
    sent_at: datetime
    text: str = ""
    button_id: str = ""
    media_id: str = ""
    media_mime: str = ""


@dataclass
class Status:
    id: str
    status: str
    at: datetime
    error_code: str = ""
    error_title: str = ""


@dataclass
class Change:
    phone_number_id: str
    contacts: dict = field(default_factory=dict)  # wa_id -> profile name
    messages: list = field(default_factory=list)
    statuses: list = field(default_factory=list)


def _time(value):
    try:
        return datetime.fromtimestamp(int(value), tz=dt_timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return timezone.now()


def _dict(value):
    return value if isinstance(value, dict) else {}


def _list(value):
    return value if isinstance(value, list) else []


def parse_message(raw):
    raw = _dict(raw)
    wa_id, message_id = str(raw.get("from") or ""), str(raw.get("id") or "")
    if not wa_id or not message_id:
        return None
    raw_type = str(raw.get("type") or "unknown")
    message = Message(wa_id=wa_id, id=message_id, type="unsupported", raw_type=raw_type[:32],
                      sent_at=_time(raw.get("timestamp")))
    if raw_type == "text":
        message.type, message.text = "text", str(_dict(raw.get("text")).get("body") or "")
    elif raw_type == "image":
        image = _dict(raw.get("image"))
        message.type = "image"
        message.text = str(image.get("caption") or "")
        message.media_id, message.media_mime = str(image.get("id") or ""), str(image.get("mime_type") or "")
    elif raw_type == "audio":
        audio = _dict(raw.get("audio"))
        message.type = "audio"
        message.media_id, message.media_mime = str(audio.get("id") or ""), str(audio.get("mime_type") or "")
    elif raw_type == "interactive" and _dict(raw.get("interactive")).get("type") == "button_reply":
        reply = _dict(_dict(raw.get("interactive")).get("button_reply"))
        message.type = "button"
        message.button_id = str(reply.get("id") or "")[:256]
        message.text = str(reply.get("title") or "")
    elif raw_type == "button":  # quick reply on a template: treated as typed text
        message.type, message.text = "text", str(_dict(raw.get("button")).get("text") or "")
    return message


def parse_status(raw):
    raw = _dict(raw)
    if not raw.get("id") or not raw.get("status"):
        return None
    error = _dict((_list(raw.get("errors")) or [{}])[0])
    return Status(id=str(raw["id"]), status=str(raw["status"]), at=_time(raw.get("timestamp")),
                  error_code=str(error.get("code") or "")[:16],
                  error_title=str(error.get("title") or error.get("message") or ""))


def parse(payload):
    """Return the `messages` changes of a WhatsApp Business Account notification."""
    payload = _dict(payload)
    if payload.get("object") != "whatsapp_business_account":
        return []
    changes = []
    for entry in _list(payload.get("entry")):
        for raw_change in _list(_dict(entry).get("changes")):
            raw_change = _dict(raw_change)
            if raw_change.get("field") != "messages":
                continue
            value = _dict(raw_change.get("value"))
            change = Change(phone_number_id=str(_dict(value.get("metadata")).get("phone_number_id") or ""))
            for contact in _list(value.get("contacts")):
                contact = _dict(contact)
                if contact.get("wa_id"):
                    change.contacts[str(contact["wa_id"])] = str(_dict(contact.get("profile")).get("name") or "")
            change.messages = [m for m in map(parse_message, _list(value.get("messages"))) if m]
            change.statuses = [s for s in map(parse_status, _list(value.get("statuses"))) if s]
            changes.append(change)
    return changes
