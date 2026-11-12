"""Test doubles and webhook payload builders (research R16). Also used by whatsapp_simulate."""

import hashlib
import hmac
import itertools
import json
import time

from django.conf import settings

from .graph import classify_error


class FakeGraph:
    """Records every send and upload; returns wamid.FAKE<n>. Errors are scripted with fail_next()."""

    def __init__(self):
        self.sent = []  # message bodies, in send order
        self.uploads = []  # (bytes, mime)
        self.media = {}  # media_id -> (bytes, mime, file_size)
        self.failures = []  # next send() outcomes: a GraphError is raised, None lets the send through
        self.download_fails = False
        self._n = itertools.count(1)

    def fail_next(self, code=131048, transient=True, title="scripted", times=1, http_status=400, after=0):
        self.failures.extend([None] * after)
        for _ in range(times):
            error = classify_error(code=code, title=title, http_status=http_status)
            error.transient = transient
            self.failures.append(error)

    def send(self, body):
        failure = self.failures.pop(0) if self.failures else None
        if failure is not None:
            raise failure
        self.sent.append(body)
        return f"wamid.FAKE{next(self._n)}"

    def get_media(self, media_id):
        if media_id not in self.media:
            raise classify_error(code=100, title="Unknown media", http_status=404)
        content, mime, size = self.media[media_id]
        return {"url": f"https://fake.lookaside/{media_id}", "mime_type": mime,
                "file_size": size if size is not None else len(content)}

    def download(self, url):
        if self.download_fails:
            raise classify_error(title="download failed", http_status=None)
        return self.media[url.rsplit("/", 1)[-1]][0]

    def upload_media(self, content, mime):
        self.uploads.append((content, mime))
        return f"media.FAKE{len(self.uploads)}"

    def add_media(self, media_id, content, mime="image/jpeg", file_size=None):
        self.media[media_id] = (content, mime, file_size)
        return media_id

    # helpers for assertions
    def of_type(self, kind):
        return [body for body in self.sent if body.get("type") == kind]

    @property
    def texts(self):
        return [body["text"]["body"] for body in self.of_type("text")]


# --- Webhook payloads (contracts/webhook.md) ------------------------------------------------------

_ids = itertools.count(1)


def _wamid():
    return f"wamid.TEST{next(_ids)}"


def envelope(messages=(), statuses=(), wa_id="255742000331", name="Asha", phone_number_id=None):
    value = {
        "messaging_product": "whatsapp",
        "metadata": {"display_phone_number": "255700000000",
                     "phone_number_id": phone_number_id or settings.WHATSAPP_PHONE_NUMBER_ID},
    }
    if messages:
        value["contacts"] = [{"profile": {"name": name}, "wa_id": wa_id}]
        value["messages"] = list(messages)
    if statuses:
        value["statuses"] = list(statuses)
    return {"object": "whatsapp_business_account",
            "entry": [{"id": "WABA_ID", "changes": [{"field": "messages", "value": value}]}]}


def _message(kind, wa_id, sent_at, message_id, **content):
    return {"from": wa_id, "id": message_id or _wamid(),
            "timestamp": str(int(sent_at if sent_at is not None else time.time())),
            "type": kind, **content}


def text_message(body, wa_id="255742000331", sent_at=None, message_id=None, name="Asha", **kw):
    message = _message("text", wa_id, sent_at, message_id, text={"body": body})
    return envelope([message], wa_id=wa_id, name=name, **kw)


def image_message(media_id, caption=None, mime="image/jpeg", wa_id="255742000331", sent_at=None,
                  message_id=None, **kw):
    image = {"id": media_id, "mime_type": mime, "sha256": "x"}
    if caption:
        image["caption"] = caption
    return envelope([_message("image", wa_id, sent_at, message_id, image=image)], wa_id=wa_id, **kw)


def audio_message(media_id, mime="audio/ogg; codecs=opus", wa_id="255742000331", sent_at=None,
                  message_id=None, **kw):
    audio = {"id": media_id, "mime_type": mime, "voice": True}
    return envelope([_message("audio", wa_id, sent_at, message_id, audio=audio)], wa_id=wa_id, **kw)


def button_reply(button_id, title="Thibitisha", wa_id="255742000331", sent_at=None, message_id=None, **kw):
    interactive = {"type": "button_reply", "button_reply": {"id": button_id, "title": title}}
    return envelope([_message("interactive", wa_id, sent_at, message_id, interactive=interactive)],
                    wa_id=wa_id, **kw)


def unsupported_message(kind="sticker", wa_id="255742000331", sent_at=None, message_id=None, **kw):
    return envelope([_message(kind, wa_id, sent_at, message_id, **{kind: {"id": "x"}})], wa_id=wa_id, **kw)


def status_update(wa_message_id, status="delivered", recipient="255742000331", error=None, timestamp=None):
    item = {"id": wa_message_id, "status": status, "recipient_id": recipient,
            "timestamp": str(int(timestamp or time.time()))}
    if error:
        item["errors"] = [error]
    return envelope(statuses=[item])


def sign(raw, secret=None):
    secret = settings.WHATSAPP_APP_SECRET if secret is None else secret
    return "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


def signed_post(client, payload, secret=None, path="/api/whatsapp/webhook/"):
    raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    return client.post(path, data=raw, content_type="application/json",
                       HTTP_X_HUB_SIGNATURE_256=sign(raw, secret))
