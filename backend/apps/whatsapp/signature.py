"""Webhook authentication (research R1): HMAC-SHA256 over the raw body, constant-time compares."""

import hashlib
import hmac

from django.conf import settings

PREFIX = "sha256="


def verify_signature(raw: bytes, header) -> bool:
    secret = settings.WHATSAPP_APP_SECRET
    if not secret or not header or not header.startswith(PREFIX):
        return False
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header[len(PREFIX):].strip().lower())


def verify_token(given) -> bool:
    expected = settings.WHATSAPP_VERIFY_TOKEN
    if not expected or not given:
        return False
    return hmac.compare_digest(expected.encode(), str(given).encode())
