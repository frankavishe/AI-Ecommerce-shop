"""Meta Graph API client for WhatsApp (contracts/outbound.md).

Everything else calls get_client(), which tests replace with use_fake(FakeGraph()). With
WHATSAPP_FAKE_GRAPH set in DEBUG, a LoggingGraph logs the payloads instead of calling Meta.
"""

import json
import logging
import mimetypes
import uuid
from pathlib import Path

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)

TRANSIENT_CODES = {1, 2, 4, 80007, 130429, 131016, 131048, 131056}
RECIPIENT_CODES = {131026, 131047}
TIMEOUT = 20


class NotConfigured(Exception):
    """WHATSAPP_ACCESS_TOKEN or WHATSAPP_PHONE_NUMBER_ID is empty."""


class GraphError(Exception):
    def __init__(self, code=None, title="", http_status=None, transient=False):
        super().__init__(f"Graph error {code} ({http_status}): {title}")
        self.code = code
        self.title = title or ""
        self.http_status = http_status
        self.transient = transient

    @property
    def recipient(self):
        """A permanent error about this recipient: the rest of the batch is skipped."""
        return self.code in RECIPIENT_CODES


def classify_error(code=None, title="", http_status=None):
    """Build a GraphError, deciding whether a retry can help (R10 error classes)."""
    if code in TRANSIENT_CODES:
        transient = True
    elif code is not None:
        transient = False
    else:
        # no Graph code: a network error/timeout (no status) or a server error retries
        transient = http_status is None or http_status >= 500
    return GraphError(code=code, title=title, http_status=http_status, transient=transient)


def _error_from_response(response):
    try:
        error = response.json().get("error") or {}
    except ValueError:
        error = {}
    details = (error.get("error_data") or {}).get("details") or ""
    title = error.get("message") or error.get("title") or response.reason_phrase
    if details:
        title = f"{title}: {details}"
    return classify_error(code=error.get("code"), title=title[:500], http_status=response.status_code)


class GraphClient:
    def __init__(self, transport=None):
        if not settings.WHATSAPP_ACCESS_TOKEN or not settings.WHATSAPP_PHONE_NUMBER_ID:
            raise NotConfigured("WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID must be set.")
        self.base = f"{settings.WHATSAPP_GRAPH_URL.rstrip('/')}/{settings.WHATSAPP_GRAPH_VERSION}"
        self.number_id = settings.WHATSAPP_PHONE_NUMBER_ID
        self.http = httpx.Client(
            headers={"Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}"},
            timeout=TIMEOUT, transport=transport,
        )

    def _request(self, method, url, **kwargs):
        try:
            response = self.http.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise classify_error(title=str(exc) or exc.__class__.__name__) from exc
        if response.status_code >= 400:
            raise _error_from_response(response)
        return response

    def send(self, body):
        data = self._request("POST", f"{self.base}/{self.number_id}/messages", json=body).json()
        return data["messages"][0]["id"]

    def get_media(self, media_id):
        data = self._request("GET", f"{self.base}/{media_id}").json()
        return {"url": data.get("url"), "mime_type": data.get("mime_type", ""),
                "file_size": data.get("file_size")}

    def download(self, url):
        return self._request("GET", url).content

    def upload_media(self, content, mime):
        data = self._request(
            "POST", f"{self.base}/{self.number_id}/media",
            data={"messaging_product": "whatsapp", "type": mime},
            files={"file": ("upload", content, mime)},
        ).json()
        return data["id"]


SIM_MEDIA_PREFIX = "sim."


def sim_media_dir():
    """Where whatsapp_simulate puts the files it sends, so any process can serve them."""
    return Path(settings.MEDIA_ROOT) / "whatsapp" / "sim"


class LoggingGraph:
    """DEBUG stand-in that logs sends and serves media registered by whatsapp_simulate."""

    def __init__(self):
        self.media = {}  # media_id -> (bytes, mime)

    def add_media(self, media_id, content, mime):
        self.media[media_id] = (content, mime)

    def _media(self, media_id):
        if media_id in self.media:
            return self.media[media_id]
        if media_id.startswith(SIM_MEDIA_PREFIX):  # sim.<hex>.<ext>, written by whatsapp_simulate
            path = sim_media_dir() / media_id.removeprefix(SIM_MEDIA_PREFIX)
            if path.is_file() and path.parent == sim_media_dir():
                return path.read_bytes(), mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return b"", "application/octet-stream"

    def send(self, body):
        wamid = f"wamid.LOG{uuid.uuid4().hex}"  # unique across restarts (wa_message_id is unique)
        logger.warning("WhatsApp (fake) send %s: %s", wamid, json.dumps(body, ensure_ascii=False))
        return wamid

    def get_media(self, media_id):
        content, mime = self._media(media_id)
        return {"url": f"fake://{media_id}", "mime_type": mime, "file_size": len(content)}

    def download(self, url):
        return self._media(url.removeprefix("fake://"))[0]

    def upload_media(self, content, mime):
        media_id = f"media.LOG{uuid.uuid4().hex}"
        logger.warning("WhatsApp (fake) upload %s (%s, %d bytes)", media_id, mime, len(content))
        return media_id


_fake = None
_logging = None


def use_fake(fake):
    global _fake
    _fake = fake


def reset_fake():
    use_fake(None)


def get_client():
    global _logging
    if _fake is not None:
        return _fake
    if settings.WHATSAPP_FAKE_GRAPH and settings.DEBUG:
        if _logging is None:
            _logging = LoggingGraph()
        return _logging
    return GraphClient()
