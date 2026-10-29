"""ClickPesa API client. There is no sandbox: every live call moves real money (research R5)."""

import hashlib
import hmac
import json
import logging

import httpx
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

TOKEN_CACHE_KEY = "clickpesa:token"
TOKEN_TTL_SECONDS = 55 * 60  # tokens live 1 hour; mints are limited to one per 3 minutes


class PaymentProviderUnavailable(Exception):
    pass


def _canonical(value):
    if isinstance(value, dict):
        return {k: _canonical(value[k]) for k in sorted(value)}
    if isinstance(value, list):
        return [_canonical(v) for v in value]
    return value


def checksum(payload, key):
    body = {k: v for k, v in payload.items() if k not in ("checksum", "checksumMethod")}
    message = json.dumps(_canonical(body), separators=(",", ":"), ensure_ascii=False)
    return hmac.new(key.encode(), message.encode(), hashlib.sha256).hexdigest()


def verify_checksum(payload, received, key):
    return bool(received) and hmac.compare_digest(checksum(payload, key), str(received).lower())


def _amount(value):
    return str(int(value)) if value == int(value) else str(value)


class ClickPesaClient:
    def __init__(self, transport=None, timeout=15.0):
        self.base_url = settings.CLICKPESA_BASE_URL.rstrip("/")
        self.client_id = settings.CLICKPESA_CLIENT_ID
        self.api_key = settings.CLICKPESA_API_KEY
        self.checksum_key = settings.CLICKPESA_CHECKSUM_KEY
        self.transport = transport
        self.timeout = timeout

    @property
    def configured(self):
        return bool(self.client_id and self.api_key)

    def _request(self, method, path, **kwargs):
        if not self.configured:
            raise PaymentProviderUnavailable("ClickPesa credentials are not configured.")
        try:
            with httpx.Client(transport=self.transport, timeout=self.timeout) as http:
                response = http.request(method, f"{self.base_url}{path}", **kwargs)
        except httpx.HTTPError as exc:
            logger.warning("ClickPesa %s %s failed: %s", method, path, exc)
            raise PaymentProviderUnavailable(str(exc)) from exc
        return response

    def _check(self, response):
        if response.is_error:
            logger.warning("ClickPesa error %s: %s", response.status_code, response.text[:500])
            raise PaymentProviderUnavailable(f"ClickPesa returned {response.status_code}.")
        return response.json()

    def token(self):
        token = cache.get(TOKEN_CACHE_KEY)
        if token:
            return token
        response = self._request(
            "POST", "/generate-token",
            headers={"client-id": self.client_id, "api-key": self.api_key},
        )
        data = self._check(response)
        token = data.get("token")
        if not token:
            raise PaymentProviderUnavailable("ClickPesa did not return a token.")
        cache.set(TOKEN_CACHE_KEY, token, TOKEN_TTL_SECONDS)
        return token

    def _authed(self, method, path, **kwargs):
        return self._request(method, path, headers={"Authorization": self.token()}, **kwargs)

    def create_checkout_link(self, reference, amount, name, phone, description):
        body = {
            "totalPrice": _amount(amount),
            "orderReference": reference,
            "orderCurrency": "TZS",
            "customerName": name,
            "customerPhone": phone.lstrip("+"),
            "description": description,
        }
        if self.checksum_key:
            body["checksum"] = checksum(body, self.checksum_key)
        data = self._check(self._authed("POST", "/checkout-link/generate-checkout-url", json=body))
        link = data.get("checkoutLink")
        if not link:
            raise PaymentProviderUnavailable("ClickPesa did not return a checkout link.")
        return link

    def query_payments(self, reference):
        """Return ClickPesa's payment records for a reference ([] when it has none yet)."""
        response = self._authed("GET", f"/payments/{reference}")
        if response.status_code == 404:
            return []
        data = self._check(response)
        return data if isinstance(data, list) else [data]


def get_client():
    return ClickPesaClient()
