"""Send a signed, simulated WhatsApp message to the local webhook (DEBUG only, quickstart §2).

    python manage.py whatsapp_simulate --from 255742000331 --text "nataka viatu vyekundu"
    python manage.py whatsapp_simulate --image shoe.jpg            # or --audio note.ogg
    python manage.py whatsapp_simulate --button confirm:<prompt id>
    python manage.py whatsapp_simulate --inline --timing --text "habari"

The payload is built like Meta's (apps/whatsapp/testing.py) and signed with WHATSAPP_APP_SECRET.
Media files are copied under MEDIA_ROOT/whatsapp/sim/ and sent as `sim.<name>` media ids, which
the WHATSAPP_FAKE_GRAPH stand-in serves in any process. --inline posts through Django's test client
in this process instead of over HTTP. --timing waits for the reply and prints the seconds from the
webhook to the reply being queued, then the reply itself.
"""

import json
import mimetypes
import shutil
import time
import uuid
from pathlib import Path

import httpx
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.test import Client

from apps.whatsapp import graph, testing
from apps.whatsapp.models import WhatsAppOutboundMessage as Out

DEFAULT_URL = "http://localhost:8000/api/whatsapp/webhook/"


class Command(BaseCommand):
    help = "Simulate an inbound WhatsApp message (text, photo, voice note or button tap). DEBUG only."

    def add_arguments(self, parser):
        parser.add_argument("--from", dest="wa_id", default="255742000331", help="Sender wa_id (digits).")
        parser.add_argument("--name", default="Asha", help="Sender profile name.")
        kind = parser.add_mutually_exclusive_group(required=True)
        kind.add_argument("--text")
        kind.add_argument("--image", type=Path, metavar="PATH")
        kind.add_argument("--audio", type=Path, metavar="PATH")
        kind.add_argument("--button", metavar="ID", help="A button id from the log, e.g. confirm:<uuid>.")
        parser.add_argument("--caption", default=None, help="Caption for --image.")
        parser.add_argument("--url", default=DEFAULT_URL, help="Webhook URL (ignored with --inline).")
        parser.add_argument("--inline", action="store_true", help="Call the webhook view in this process.")
        parser.add_argument("--timing", action="store_true",
                            help="Wait for the reply; print webhook -> reply-queued seconds and the reply.")
        parser.add_argument("--wait", type=float, default=None,
                            help="Seconds to wait for the reply with --timing (default AI_CHAT_TIMEOUT + 30).")

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("whatsapp_simulate only runs with DEBUG=True.")
        if not settings.WHATSAPP_APP_SECRET:
            raise CommandError("Set WHATSAPP_APP_SECRET (and WHATSAPP_PHONE_NUMBER_ID) first.")
        wa_id, message_id = options["wa_id"], f"wamid.SIM{uuid.uuid4().hex}"
        common = {"wa_id": wa_id, "message_id": message_id}

        if options["text"] is not None:
            payload = testing.text_message(options["text"], name=options["name"], **common)
        elif options["button"]:
            payload = testing.button_reply(options["button"], name=options["name"], **common)
        elif options["image"]:
            media_id, mime = self.stage_media(options["image"])
            payload = testing.image_message(media_id, caption=options["caption"], mime=mime, **common)
        else:
            media_id, mime = self.stage_media(options["audio"])
            payload = testing.audio_message(media_id, mime=mime, **common)
        payload["entry"][0]["changes"][0]["value"]["contacts"][0]["profile"]["name"] = options["name"]

        started = time.monotonic()
        since = Out.objects.order_by("-id").values_list("id", flat=True).first() or 0
        status = self.post(payload, options)
        self.stdout.write(f"Sent {message_id} from {wa_id}: HTTP {status}")
        if status != 200:
            raise CommandError("The webhook refused the message (check the secret and phone number id).")
        if options["timing"]:
            self.report(wa_id, since, started, options["wait"])

    def stage_media(self, path):
        if not path.is_file():
            raise CommandError(f"No such file: {path}")
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        name = f"{uuid.uuid4().hex}{path.suffix.lower()}"
        target = graph.sim_media_dir() / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        media_id = graph.SIM_MEDIA_PREFIX + name
        client = graph.get_client()
        if hasattr(client, "add_media"):  # a fake in this process: register the bytes directly
            client.add_media(media_id, target.read_bytes(), mime)
        return media_id, mime

    def post(self, payload, options):
        raw = json.dumps(payload).encode()
        headers = {"X-Hub-Signature-256": testing.sign(raw)}
        if options["inline"]:
            return Client(HTTP_HOST=settings.ALLOWED_HOSTS[0] if settings.ALLOWED_HOSTS else "localhost").post(
                "/api/whatsapp/webhook/", data=raw, content_type="application/json",
                HTTP_X_HUB_SIGNATURE_256=headers["X-Hub-Signature-256"]).status_code
        try:
            response = httpx.post(options["url"], content=raw, timeout=30,
                                  headers={**headers, "Content-Type": "application/json"})
        except httpx.HTTPError as exc:
            raise CommandError(f"Could not reach {options['url']}: {exc}") from exc
        return response.status_code

    def printable(self, text):
        """Replies carry emoji (the 🎤 heard line); a Windows console may not encode them."""
        encoding = getattr(self.stdout._out, "encoding", None) or "utf-8"
        return text.encode(encoding, "replace").decode(encoding)

    def report(self, wa_id, since, started, wait):
        """Wait for the reply batch to be queued, then print the timing and what was queued."""
        wait = settings.AI_CHAT_TIMEOUT + 30 if wait is None else wait
        deadline = started + wait
        rows = []
        while time.monotonic() < deadline:
            rows = list(Out.objects.filter(contact__wa_id=wa_id, id__gt=since).order_by("id"))
            if rows:
                break
            time.sleep(0.5)
        if not rows:
            self.stdout.write(self.style.WARNING(f"No reply queued within {wait:.0f} s."))
            return
        elapsed = time.monotonic() - started
        time.sleep(1)  # the rest of the batch is written in the same transaction; take it all
        rows = list(Out.objects.filter(contact__wa_id=wa_id, batch=rows[0].batch).order_by("position"))
        self.stdout.write(self.style.SUCCESS(f"Reply queued after {elapsed:.1f} s ({len(rows)} message(s)):"))
        for row in rows:
            self.stdout.write(self.printable(f"  [{row.kind}] {row.text}"))
            if row.kind == Out.Kind.BUTTONS:
                for button in row.body["interactive"]["action"]["buttons"]:
                    self.stdout.write(f"    --button {button['reply']['id']}  ({button['reply']['title']})")
