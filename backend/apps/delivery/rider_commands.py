"""Common rider messages handled by the server, without the model (contracts/rider-tools.md "Server commands").

"kazi zangu?", "nimechukua <number>", "niko njiani", "nimefikisha <number>", "imeshindikana <number>,
<reason>", "niko off" and "niko tayari" run the rider tool directly through ai.tools.run_tool (same
validation and transaction as a model call) and answer with the tool's fixed text. Anything else,
or a message that matches more than one command, goes to the model as before.
"""

import re
import time
from dataclasses import dataclass, field

from apps.ai.models import ChatMessage, Conversation
from apps.ai.tools import RIDER, ToolContext, run_tool
from apps.orders.services import ORDER_NUMBER_ALPHABET

from . import texts
from .models import ACTIVE, Delivery

MAX_WORDS = 15

INTENTS = {
    "jobs": r"\bkazi zangu\b|\bmy jobs\b|^(kazi|jobs)$",
    "picked_up": r"\bnimechukua\b|\bnimebeba\b|\bpicked (it )?up\b",
    "on_the_way": r"\bniko njiani\b|\bnipo njiani\b|\bon (my|the) way\b",
    "delivered": r"\bnimefikisha\b|\bnimeifikisha\b|\bnimemfikishia\b|\bdelivered\b",
    "failed": r"\bimeshindikana\b|\bnimeshindwa\b|\bfailed\b|\bcould ?n.?t deliver\b",
    "unavailable": r"\bniko off\b|\bnipo off\b|\bsipatikani\b|\bunavailable\b|\bnot available\b|\bi'?m off\b",
    "available": r"\bniko tayari\b|\bnipo tayari\b|(?<!not )\bavailable\b",
}
_INTENTS = {name: re.compile(pattern) for name, pattern in INTENTS.items()}
_NUMBER = re.compile(rf"#?\b([{ORDER_NUMBER_ALPHABET}{ORDER_NUMBER_ALPHABET.lower()}]{{8}})\b")


@dataclass
class Command:
    intent: str
    numbers: list = field(default_factory=list)  # tokens that look like order numbers (digit or capitals)
    maybe: list = field(default_factory=list)  # other 8-letter tokens: used only if they are this rider's job
    reason: str = ""


def _normalize(text):
    return re.sub(r"\s+", " ", re.sub(r"[?!.,;:]+", " ", (text or "").lower())).strip()


def parse(text):
    """The one command in this message, or None (no command, several, or too long)."""
    text = (text or "").strip()
    if not text or len(text.split()) > MAX_WORDS:
        return None
    matched = [name for name, pattern in _INTENTS.items() if pattern.search(_normalize(text))]
    if len(matched) != 1:
        return None
    intent = matched[0]
    tokens = list(dict.fromkeys(m.group(1) for m in _NUMBER.finditer(text)))
    likely = [t for t in tokens if t.isupper() or any(c.isdigit() for c in t)]
    command = Command(intent, numbers=[t.upper() for t in likely],
                      maybe=[t.upper() for t in tokens if t not in likely])
    if intent == "failed":
        rest = re.sub(INTENTS["failed"], " ", text, flags=re.I)
        for token in likely:
            rest = re.sub(rf"#?\b{re.escape(token)}\b", " ", rest, flags=re.I)
        rest = re.sub(r"^[\s,.:;-]*(?:(?:ya|wa|la|kwa|oda|order)\b[\s,.:;-]*)*", "", rest, flags=re.I)
        command.reason = re.sub(r"\s+", " ", rest).strip(" ,.:;-")[:255]
    return command


def _pick_number(rider, command):
    """A number the rider typed: one of their jobs if any candidate is, else the first likely one."""
    candidates = command.numbers + command.maybe
    if not candidates:
        return None
    mine = set(Delivery.objects.filter(rider=rider, order__number__in=candidates)
               .values_list("order__number", flat=True))
    return next((n for n in candidates if n in mine), None) or next(iter(command.numbers), None)


def control(job):
    """CONTROL_HANDLERS hook (after rider_stop_control): answer a rider command without the model."""
    from apps.whatsapp import processing
    from apps.whatsapp.models import WhatsAppInboundMessage as Inbound

    if job.rider is None or job.inbound.type != Inbound.Type.TEXT:
        return None
    if job.conversation.state == Conversation.State.NEEDS_HUMAN:
        return None  # staff took over: processing records the message for them
    command = parse(job.inbound.text)
    if command is None:
        return None

    processing.record(job)  # stores the rider's message and sets the conversation language
    conversation = job.conversation
    lang = conversation.language
    ctx = ToolContext(conversation=conversation, user=job.rider, role=RIDER)
    calls = []

    def call(name, args):
        begun = time.perf_counter()
        ok, result, parsed = run_tool(ctx, name, args)
        calls.append({"name": name, "arguments": parsed if parsed is not None else args, "ok": ok,
                      "ms": round((time.perf_counter() - begun) * 1000),
                      **({} if ok else {"error": result.get("error", "")})})

    if command.intent == "jobs":
        call("my_jobs", {})
    elif command.intent in ("available", "unavailable"):
        call("set_availability", {"available": command.intent == "available"})
    else:
        number = _pick_number(job.rider, command)
        if number is None:
            active = list(Delivery.objects.filter(rider=job.rider, status__in=ACTIVE)
                          .select_related("order").order_by("assigned_at", "id"))
            if len(active) == 1:
                number = active[0].order.number
            else:
                if active:
                    ctx.add_reply(texts.text("which_job", lang))
                ctx.add_reply(texts.jobs_text(active, lang))
        if number is not None:
            args = {"order_number": number, "status": command.intent}
            if command.intent == "failed" and command.reason:
                args["reason"] = command.reason
            call("update_delivery", args)

    reply = ctx.fixed_reply
    ChatMessage.objects.create(conversation=conversation, role=ChatMessage.Role.ASSISTANT, text=reply,
                               language=lang, tool_calls=calls, payload=ctx.payload(), steps=0, latency_ms=0)
    processing.send_system(job, reply)
    if job.contact.language != lang:
        job.contact.language = lang
        job.contact.save(update_fields=["language", "updated_at"])
    return Inbound.Status.ANSWERED, ""
