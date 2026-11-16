"""Confirm / Change buttons after a checkout summary (FR-016a, research R6) and the server-built
payment message (FR-016, research R8).

A Confirm tap places the order by running the same 003 `checkout` tool a typed "yes" would, but
with no model in the loop: the small CPU model is unreliable at calling confirm=true. The tap is
only honoured when it belongs to the newest summary of this conversation, is under
CONFIRM_WINDOW old, and the cart, details and totals still match what the shopper saw.

Taps of one number are already processed one at a time (drain_contact holds the number's advisory
lock), so a double tap is seen as "prompt already has an order" and never places a second one.
"""

import hashlib
import json
import logging
import uuid

from django.db import transaction
from django.utils import timezone

from apps.ai import prompts, tools
from apps.ai.models import ChatMessage
from apps.catalog.models import Product
from apps.orders.models import Order
from apps.payments.models import Payment

from . import outbound, processing, texts
from .models import (
    WhatsAppCheckoutPrompt as Prompt,
    WhatsAppInboundMessage as Inbound,
    WhatsAppOrder,
    WhatsAppOutboundMessage as Out,
)

logger = logging.getLogger(__name__)

S = Inbound.Status
CONFIRM, CHANGE = "confirm", "change"


# --- Fingerprint and prompt -----------------------------------------------------------------------


def fingerprint(summary):
    """sha256 over what the shopper agreed to: lines, details, method, network, fee and total."""
    details = summary.get("details") or {}
    data = {
        "lines": sorted([int(pid), int(qty), tools.money(price)] for pid, qty, price in summary["lines"]),
        "details": {key: " ".join(str(details.get(key) or "").split()).lower() for key in tools.DETAIL_FIELDS},
        "method": summary.get("method") or "",
        "network": summary.get("network") or "",
        "fee": tools.money(summary["fee"]),
        "total": tools.money(summary["total"]),
    }
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def send_prompt(job, summary, batch):
    """Store a prompt for this summary and queue the buttons (inside the caller's batch)."""
    lang = job.lang
    prompt = Prompt.objects.create(
        conversation=job.conversation, contact=job.contact, fingerprint=fingerprint(summary),
        method=summary.get("method") or "", network=summary.get("network") or "", total=summary["total"],
    )
    body = texts.text("confirm_body", lang, total=texts.format_tzs(summary["total"]),
                      fee=texts.format_tzs(summary["fee"]))
    outbound.queue_buttons(
        job.contact, body,
        [(f"{CONFIRM}:{prompt.pk}", texts.text("confirm_button", lang)),
         (f"{CHANGE}:{prompt.pk}", texts.text("change_button", lang))],
        Out.Trigger.ASSISTANT, job.conversation, batch=batch,
    )
    return prompt


def summary_lines(summary, lang):
    """A short server summary ("1 × Red Sneakers — 45,000 TZS") for a refreshed prompt."""
    names = dict(Product.objects.filter(pk__in=[pid for pid, _, _ in summary["lines"]]).values_list("pk", "name"))
    lines = [f"{qty} × {names.get(pid, '?')} — {texts.format_tzs(price * qty)} TZS"
             for pid, qty, price in summary["lines"]]
    return "\n".join([texts.text("summary_outdated", lang), *lines])


# --- Payment message (R8) -------------------------------------------------------------------------


def payment_message(order, payment, lang):
    """The server's own payment text: the order number and DB total, plus the card link or the
    mobile-money PIN prompt note."""
    total = texts.format_tzs(order.total)
    link = (payment or {}).get("checkout_link")
    if (payment or {}).get("method") == Payment.Method.CARD and link:
        return texts.text("payment_card", lang, number=order.number, total=total, link=link)
    return texts.text("payment_mobile", lang, number=order.number, total=total, phone=order.contact_phone)


def link_order(contact, order):
    if order is not None:
        WhatsAppOrder.objects.get_or_create(order=order, defaults={"contact": contact})


# --- Hooks into processing.py ---------------------------------------------------------------------


def after_turn(job, reply):
    """A typed confirm placed an order: tie it to this number (US2, US5)."""
    link_order(job.contact, job.conversation.last_order)


def reply_extras(job, reply, batch):
    """The payment text after a turn that started a payment, and buttons after a summary (last)."""
    payment = reply.payload.get("payment")
    order_brief = reply.payload.get("order")
    if payment and order_brief:
        order = Order.objects.filter(number=order_brief["number"]).first()
        if order is not None:
            outbound.queue_text(job.contact, payment_message(order, payment, job.lang), Out.Trigger.PAYMENT,
                                job.conversation, batch=batch)
    if reply.summary:
        send_prompt(job, reply.summary, batch)


# --- Button taps ----------------------------------------------------------------------------------


def _parse(button_id):
    kind, _, raw = (button_id or "").partition(":")
    try:
        return kind, uuid.UUID(raw)
    except ValueError:
        return kind, None


def handle_button(job):
    kind, prompt_id = _parse(job.inbound.button_id)
    prompt = None
    if kind in (CONFIRM, CHANGE) and prompt_id is not None:
        prompt = Prompt.objects.filter(pk=prompt_id, contact=job.contact,
                                       conversation=job.conversation).first()
    if prompt is None:
        return processing.reply_fixed(job, "button_expired", S.REJECTED)
    if kind == CHANGE:
        return processing.run_turn(job, texts.text("change_request", job.lang), button=CHANGE)
    return confirm(job, prompt)


def _context(job):
    user = job.contact.user
    return tools.ToolContext(
        conversation=job.conversation, user=user, role=tools.CUSTOMER if user else tools.GUEST,
        verified_phone=job.contact.phone, phone_orders=processing.phone_orders(job.contact),
    )


def _checkout_args(prompt, confirm_order):
    args = {"confirm": confirm_order, "method": prompt.method or Payment.Method.MOBILE_MONEY}
    if prompt.network:
        args["network"] = prompt.network
    return args


def _store_answer(job, text, ctx, calls):
    return ChatMessage.objects.create(
        conversation=job.conversation, role=ChatMessage.Role.ASSISTANT, text=text,
        language=job.lang, tool_calls=calls, payload=ctx.payload(),
    )


def _send(job, items):
    """Queue [(kind, value)] as one batch. kind: "text" | "payment" | "prompt"."""
    try:
        with transaction.atomic():
            batch = uuid.uuid4()
            for kind, value in items:
                if kind == "prompt":
                    send_prompt(job, value, batch)
                else:
                    trigger = Out.Trigger.PAYMENT if kind == "payment" else Out.Trigger.SYSTEM
                    outbound.queue_text(job.contact, value, trigger, job.conversation, batch=batch)
            outbound.flush(batch)
    except outbound.WindowClosed:
        logger.warning("WhatsApp window closed for %s; button answer not sent.", job.contact.phone)
        job.inbound.error = "window_closed"


def _run(ctx, args):
    ok, result, parsed = tools.run_tool(ctx, "checkout", args)
    call = {"name": "checkout", "arguments": parsed, "ok": ok, "ms": 0}
    if not ok:
        call["error"] = result.get("error", "")
    return ok, result, call


def _pay_answer(job, ctx, order, result):
    """The text after an order exists: the payment message, or the reason the payment didn't start."""
    if ctx.payment:
        return "payment", payment_message(order, ctx.payment, job.lang)
    return "text", str(result.get("error") or prompts_fallback(job))


def prompts_fallback(job):
    return prompts.fallback("empty", job.lang)


def confirm(job, prompt):
    lang = job.lang
    processing.record(job, text=f"✓ {texts.text('confirm_button', lang)}", button=CONFIRM)
    ctx = _context(job)

    # 1. A repeat tap: the order exists. Resend its payment text (retrying a payment that failed).
    if prompt.order_id is not None:
        order = prompt.order
        latest = order.payments.first()
        if latest is not None and latest.status in (Payment.Status.PENDING, Payment.Status.SUCCESS):
            payment = {"method": latest.method, "checkout_link": latest.checkout_link}
            text = payment_message(order, payment, lang)
            _store_answer(job, text, ctx, [])
            _send(job, [("payment", text)])
            return S.ANSWERED, ""
        ok, result, call = _run(ctx, _checkout_args(prompt, True))
        kind, text = _pay_answer(job, ctx, order, result)
        _store_answer(job, text, ctx, [call])
        _send(job, [(kind, text)])
        return S.ANSWERED, ""

    # 2./3. Newest, recent, and the same cart, details and totals as the summary the shopper saw.
    newest = Prompt.objects.filter(conversation=job.conversation).order_by("-created_at").first()
    recent = timezone.now() - prompt.created_at < tools.CONFIRM_WINDOW
    ok, result, summary_call = _run(ctx, _checkout_args(prompt, False))
    summary = ctx.checkout_summary
    if newest != prompt or not recent or summary is None or fingerprint(summary) != prompt.fingerprint:
        if summary is None:  # nothing to confirm any more (empty cart, missing details)
            text = texts.text("button_expired", lang)
            _store_answer(job, text, ctx, [summary_call])
            _send(job, [("text", text)])
            return S.ANSWERED, "prompt_stale"
        text = summary_lines(summary, lang)
        _store_answer(job, text, ctx, [summary_call])
        _send(job, [("text", text), ("prompt", summary)])
        return S.ANSWERED, "prompt_stale"

    # 4. Place the order with the server checkout tool (no model).
    ctx.checkout_summary = None
    ok, result, call = _run(ctx, _checkout_args(prompt, True))
    job.conversation.refresh_from_db()
    order = job.conversation.last_order if ctx.order else None
    if order is None:
        text = str(result.get("error") or prompts_fallback(job))
        _store_answer(job, text, ctx, [summary_call, call])
        _send(job, [("text", text)])
        return S.ANSWERED, "checkout_failed"

    # 5. Remember the order on the prompt, tie it to this number, send the payment text.
    Prompt.objects.filter(pk=prompt.pk).update(order=order)
    link_order(job.contact, order)
    kind, text = _pay_answer(job, ctx, order, result)
    _store_answer(job, text, ctx, [summary_call, call])
    _send(job, [(kind, text)])
    return S.ANSWERED, ""
