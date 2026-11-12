"""Linking a WhatsApp number to a web account (FR-008, research R13, contracts/link-api.md).

The account page issues a one-time `LINK-XXXXXX` code (only its sha256 is stored); the shopper
sends it from WhatsApp and the processing pipeline redeems it before the assistant runs.
"""

import hashlib
import re
import secrets
from datetime import timedelta
from urllib.parse import quote

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.orders.models import Cart
from apps.orders.services import merge_carts

from . import processing
from .models import (
    WhatsAppContact,
    WhatsAppInboundMessage as Inbound,
    WhatsAppLinkAttempt,
    WhatsAppLinkCode,
)

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I
CODE_LENGTH = 6
CODE_LIFETIME = timedelta(minutes=10)
CODE_RE = re.compile(r"\bLINK-([A-Z2-9]{6})\b", re.I)
MAX_WRONG_PER_HOUR = 5


class NotConfigured(Exception):
    pass


def _hash(code):
    return hashlib.sha256(code.upper().encode()).hexdigest()


def business_digits():
    return "".join(ch for ch in settings.WHATSAPP_BUSINESS_NUMBER if ch.isdigit())


def issue_code(user):
    """A fresh code for `user`; any unused older code stops working. Returns the API body."""
    if not business_digits():
        raise NotConfigured
    expires_at = timezone.now() + CODE_LIFETIME
    with transaction.atomic():
        WhatsAppLinkCode.objects.filter(user=user, used_at__isnull=True).delete()
        while True:
            code = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
            try:
                with transaction.atomic():
                    WhatsAppLinkCode.objects.create(user=user, code_hash=_hash(code), expires_at=expires_at)
                break
            except IntegrityError:  # a hash collision with another live code: draw again
                continue
    shown = f"LINK-{code}"
    return {"code": shown, "expires_at": expires_at,
            "wa_link": f"https://wa.me/{business_digits()}?text={quote(shown)}"}


def mask(phone):
    """+255742000331 -> "+255 742 *** 331"."""
    digits = (phone or "").lstrip("+")
    if len(digits) < 9:
        return phone
    return f"+{digits[:3]} {digits[3:6]} *** {digits[-3:]}"


def _detach(contact):
    """Unlink one number: it becomes a guest again in a new conversation with a new guest cart."""
    contact.user, contact.linked_at = None, None
    contact.save(update_fields=["user", "linked_at", "updated_at"])
    processing._new_conversation(contact)


def unlink(user):
    with transaction.atomic():
        for contact in WhatsAppContact.objects.select_for_update().filter(user=user):
            _detach(contact)
        type(user).objects.filter(pk=user.pk).update(whatsapp_verified=False)
    user.whatsapp_verified = False


def redeem(job, code):
    """Try a code sent from WhatsApp. Returns the reply text key."""
    contact, now = job.contact, timezone.now()
    wrong = WhatsAppLinkAttempt.objects.filter(contact=contact, created_at__gte=now - timedelta(hours=1))
    if wrong.count() >= MAX_WRONG_PER_HOUR:
        return "link_failed"
    with transaction.atomic():
        row = (WhatsAppLinkCode.objects.select_for_update().select_related("user")
               .filter(code_hash=_hash(code), used_at__isnull=True, expires_at__gt=now).first())
        if row is None:
            WhatsAppLinkAttempt.objects.create(contact=contact)
            return "link_failed"
        row.used_at, row.used_by = now, contact
        row.save(update_fields=["used_at", "used_by"])
        user = row.user
        if contact.user_id is not None and contact.user_id != user.pk:
            return "link_taken"

        for other in WhatsAppContact.objects.select_for_update().filter(user=user).exclude(pk=contact.pk):
            _detach(other)  # one number per account
        contact.user, contact.linked_at = user, now
        contact.save(update_fields=["user", "linked_at", "updated_at"])
        type(user).objects.filter(pk=user.pk).update(whatsapp_verified=True)

        conversation = job.conversation
        guest_cart = conversation.cart
        conversation.user, conversation.cart = user, None
        conversation.save(update_fields=["user", "cart", "updated_at"])
        if guest_cart is not None:
            merge_carts(Cart.objects.get_or_create(user=user)[0], guest_cart)
    return "link_ok"


def control(job):
    """CONTROL_HANDLERS step: a text with a link code is answered by the server, not the model."""
    if job.inbound.type != Inbound.Type.TEXT:
        return None
    match = CODE_RE.search(job.inbound.text or "")
    if match is None:
        return None
    key = redeem(job, match.group(1).upper())
    status = Inbound.Status.ANSWERED if key == "link_ok" else Inbound.Status.REJECTED
    return processing.reply_fixed(job, key, status, "" if key == "link_ok" else key)
