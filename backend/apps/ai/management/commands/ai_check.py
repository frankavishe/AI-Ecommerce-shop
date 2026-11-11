"""Ping every model endpoint the assistant uses (specs/003-ai-core/contracts/model-endpoints.md)."""

import io
import json
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from PIL import Image

from apps.ai import clients

PING_TOOL = {"type": "function", "function": {
    "name": "ping", "description": "Answer the user's ping. Always call this tool.",
    "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
}}


def _probe_image():
    buffer = io.BytesIO()
    Image.new("RGB", (64, 64), (200, 30, 30)).save(buffer, "JPEG")
    return buffer.getvalue()


def check_chat():
    response = clients.chat(
        [{"role": "system", "content": "You must call the ping tool. Do not answer in text."},
         {"role": "user", "content": "ping"}],
        [PING_TOOL],
    )
    if not any(call["name"] == "ping" for call in response["tool_calls"]):
        raise CommandError(f"no tool call (the model answered {json.dumps((response['content'] or '')[:60])}); "
                           "the server needs tool-call support")
    return settings.AI_CHAT_MODEL


def check_embeddings():
    [vector] = clients.embed_texts(["viatu vyekundu"])
    return f"{settings.AI_EMBED_MODEL}, {len(vector)} dims"


def check_vision():
    caption = clients.caption_image(_probe_image())
    return f"{settings.AI_VISION_MODEL}: {caption[:40]!r}"


def check_image():
    vector = clients.embed_image(_probe_image())
    return f"{settings.AI_IMAGE_EMBED_URL}, {len(vector)} dims"


CHECKS = [("chat", check_chat), ("embeddings", check_embeddings), ("vision", check_vision), ("image", check_image)]


class Command(BaseCommand):
    help = "Check that the chat, embedding, vision and image-embedding endpoints answer correctly."

    def handle(self, *args, **options):
        failed = []
        self.stdout.write(f"{'check':<12}{'result':<7}{'ms':>7}  detail")
        for name, check in CHECKS:
            started = time.perf_counter()
            try:
                detail, result = check(), "ok"
            except (clients.ModelUnavailable, CommandError) as exc:
                detail, result = str(exc)[:200], "FAIL"
                failed.append(f"{name} ({detail})")
            ms = round((time.perf_counter() - started) * 1000)
            self.stdout.write(f"{name:<12}{result:<7}{ms:>7}  {detail}")
        if failed:
            raise CommandError("Failed: " + "; ".join(failed))
