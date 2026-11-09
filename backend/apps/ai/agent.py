"""The chat loop: one shopper message in, one assistant reply out (research R2, R10, R11).

handle_message() is channel-neutral: the API view calls it now, the WhatsApp task will in 004.
"""

import json
import logging
import re
import time
from dataclasses import dataclass

from django.conf import settings

from . import clients, prompts
from .language import detect_language
from .models import ChatMessage, Conversation
from .tools import CUSTOMER, GUEST, REGISTRY, ToolContext, run_tool, tools_for

logger = logging.getLogger(__name__)

_THINK = re.compile(r"<think>.*?(</think>|$)", re.S | re.I)

_now = time.monotonic  # patched in tests


@dataclass
class AgentReply:
    message: ChatMessage
    text: str
    payload: dict
    error: str


def clean_reply(text):
    return _THINK.sub("", text or "").strip()


def _history(conversation, exclude_id):
    rows = list(
        conversation.messages.filter(role__in=[ChatMessage.Role.USER, ChatMessage.Role.ASSISTANT])
        .exclude(pk=exclude_id).order_by("-created_at", "-id")[: settings.AI_HISTORY_MESSAGES]
    )
    history = []
    for row in reversed(rows):
        text = row.text or ""
        if row.role == ChatMessage.Role.USER and (row.image or row.image_deleted):
            text = f"{text}\n[The shopper sent a photo]".strip()
        if row.role == ChatMessage.Role.ASSISTANT and row.tool_calls:
            used = ", ".join(dict.fromkeys(call["name"] for call in row.tool_calls))
            shown = ", ".join(f"{p['name']} (id {p['id']})" for p in row.payload.get("products", [])[:8])
            note = f"[Tools used: {used}." + (f" Products shown: {shown}." if shown else "") + "]"
            text = f"{note}\n{text}"
        history.append({"role": row.role, "content": text})
    return history


def _user_content(text, has_image):
    if has_image:
        return f"{text}\n[The shopper attached a photo to this message]".strip()
    return text


def _completed_actions(calls, language):
    done = []
    for call in calls:
        tool = REGISTRY.get(call["name"])
        if call["ok"] and tool is not None and tool.mutates:
            done.append(tool.label.get(language) or tool.name)
    return done


def handle_message(conversation: Conversation, text="", image=None, user=None, language=None):
    """Store the shopper's message, run the model with role-scoped tools, store and return the reply."""
    started = _now()
    deadline = started + settings.AI_CHAT_TIMEOUT
    text = (text or "").strip()

    conversation.language = language or detect_language(text, conversation.language)
    conversation.save(update_fields=["language", "updated_at"])
    lang = conversation.language
    incoming = ChatMessage.objects.create(
        conversation=conversation, role=ChatMessage.Role.USER, text=text, image=image, language=lang,
    )

    if conversation.state == Conversation.State.NEEDS_HUMAN:
        notice = prompts.HANDOFF_NOTICE[lang]
        message = ChatMessage.objects.create(
            conversation=conversation, role=ChatMessage.Role.SYSTEM_NOTE, text=notice, language=lang,
        )
        return AgentReply(message, notice, {"products": [], "cart": None, "order": None, "payment": None}, "")

    image_bytes = None
    if image is not None:
        incoming.image.open("rb")
        image_bytes = incoming.image.read()
        incoming.image.close()

    authenticated = user is not None and user.is_authenticated
    ctx = ToolContext(conversation=conversation, user=user if authenticated else None,
                      role=CUSTOMER if authenticated else GUEST, image_bytes=image_bytes)
    tools = [tool.spec() for tool in tools_for(ctx.role)]
    messages = [
        {"role": "system", "content": prompts.system_prompt(lang, settings.AI_CHAT_NO_THINK)},
        *_history(conversation, incoming.pk),
        {"role": "user", "content": _user_content(text, image_bytes is not None)},
    ]

    calls, steps, error, reply = [], 0, "", None
    try:
        while reply is None:
            if steps >= settings.AI_MAX_STEPS:
                error = "step_limit"
                break
            remaining = deadline - _now()
            if remaining <= 0:
                error = "timeout"
                break
            response = clients.chat(messages, tools, timeout=remaining)
            steps += 1
            if _now() > deadline:
                error = "timeout"
                break
            if not response["tool_calls"]:
                reply = clean_reply(response["content"])
                break
            messages.append({
                "role": "assistant",
                "content": clean_reply(response["content"]),
                "tool_calls": [
                    {"id": call["id"], "type": "function",
                     "function": {"name": call["name"], "arguments": call["arguments"]}}
                    for call in response["tool_calls"]
                ],
            })
            for call in response["tool_calls"]:
                begun = time.perf_counter()
                ok, result, args = run_tool(ctx, call["name"], call["arguments"])
                calls.append({
                    "name": call["name"], "arguments": args if args is not None else call["arguments"],
                    "ok": ok, "ms": round((time.perf_counter() - begun) * 1000),
                    **({} if ok else {"error": result.get("error", "")}),
                })
                messages.append({
                    "role": "tool", "tool_call_id": call["id"],
                    "content": prompts.wrap_data(f"tool:{call['name']}",
                                                 json.dumps(result, ensure_ascii=False, default=str)),
                })
    except clients.ModelUnavailable as exc:
        logger.warning("Chat model unavailable: %s", exc)
        error = "model_unavailable"

    if not reply:
        reply = prompts.fallback(error or "empty", lang, _completed_actions(calls, lang))
    payload = ctx.payload()
    message = ChatMessage.objects.create(
        conversation=conversation, role=ChatMessage.Role.ASSISTANT, text=reply, language=lang,
        tool_calls=calls, payload=payload, steps=steps, error=error,
        latency_ms=max(0, round((_now() - started) * 1000)),
    )
    conversation.save(update_fields=["updated_at"])
    return AgentReply(message, reply, payload, error)
