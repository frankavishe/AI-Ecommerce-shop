"""Stakaba API client (docs: apps/payments/stakaba.md).

Auth is a static `x-api-key` header; the key decides sandbox (`sk_test_`) or live (`sk_live_`).
Never log request headers: they carry the key.

Verified against the sandbox on 2026-11-02:
- POST /payments/collection -> 201 {"internalReference": "STKM...", "status": "SUCCESS" | "FAILED" | ...}
- POST /payments/card       -> 201 {"checkoutUrl": "...", "internalReference": "STKC..."}
- GET /transactions/{ref}   -> 401 "Missing bearer token" with an API key (Bearer only), so payments
  are confirmed from the collection response and the token-protected webhook instead.
- Errors: {"error", "message", "details"} (400/401/...), or FastAPI {"detail": [...]} on 422.
"""

import logging
import re
from decimal import Decimal

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)

NETWORKS = ("Mpesa", "AirtelMoney", "TigoPesa", "HaloPesa")
MOBILE_MONEY_MINIMUM = Decimal("500")

# Prefixes after the country code (255) or leading 0. Number portability means this is only a
# default; the customer can pick another network.
_PREFIXES = {
    "Mpesa": ("74", "75", "76"),
    "AirtelMoney": ("68", "69", "78"),
    "TigoPesa": ("65", "67", "71", "77"),
    "HaloPesa": ("61", "62"),
}


class PaymentProviderUnavailable(Exception):
    """Stakaba can't be reached or failed on its side (or our key is wrong). Retry later."""


class PaymentRejected(Exception):
    """Stakaba refused the request for a reason the customer can fix (number, network, amount)."""

    def __init__(self, message, code="", status=None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


def msisdn(phone):
    """+255712345678 / 0712345678 / 712345678 -> 255712345678."""
    digits = re.sub(r"\D", "", str(phone or ""))
    if digits.startswith("0") and len(digits) == 10:
        digits = "255" + digits[1:]
    elif len(digits) == 9:
        digits = "255" + digits
    return digits


def guess_network(phone):
    number = msisdn(phone)
    if not number.startswith("255"):
        return None
    prefix = number[3:5]
    for network, prefixes in _PREFIXES.items():
        if prefix in prefixes:
            return network
    return None


def whole_tzs(amount):
    """Decimal('5000.00') -> 5000. Raises PaymentRejected for fractional shillings."""
    value = Decimal(str(amount))
    if value != value.to_integral_value():
        raise PaymentRejected(
            "Mobile money needs a whole-shilling amount.", code="fractional_amount"
        )
    return int(value)


def _error_message(response):
    try:
        body = response.json()
    except ValueError:
        return "", response.text[:200]
    if not isinstance(body, dict):
        return "", str(body)[:200]
    if isinstance(body.get("detail"), list) and body["detail"]:
        first = body["detail"][0]
        field = ".".join(str(p) for p in first.get("loc", [])[1:])
        return "VALIDATION_ERROR", f"{field}: {first.get('msg', '')}".strip(": ")
    if isinstance(body.get("detail"), str):
        return "", body["detail"]
    return str(body.get("error") or ""), str(body.get("message") or "")


class StakabaClient:
    def __init__(self, transport=None, timeout=15.0):
        base = settings.STAKABA_BASE_URL.rstrip("/")
        self.base_url = base if base.endswith("/api/v1") else f"{base}/api/v1"
        self.api_key = settings.STAKABA_API_KEY
        self.transport = transport
        self.timeout = timeout

    @property
    def configured(self):
        return bool(self.api_key)

    @property
    def sandbox(self):
        return self.api_key.startswith("sk_test_")

    def _request(self, method, path, allow_404=False, **kwargs):
        if not self.configured:
            raise PaymentProviderUnavailable("Stakaba API key is not configured.")
        headers = {
            "x-api-key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        try:
            with httpx.Client(transport=self.transport, timeout=self.timeout) as http:
                response = http.request(method, f"{self.base_url}{path}", headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            logger.warning("Stakaba %s %s failed: %s", method, path, exc.__class__.__name__)
            raise PaymentProviderUnavailable(str(exc)) from exc
        if response.is_success:
            try:
                data = response.json()
            except ValueError as exc:
                raise PaymentProviderUnavailable("Stakaba returned a non-JSON response.") from exc
            return data if isinstance(data, dict) else {}

        status = response.status_code
        if status == 404 and allow_404:
            return None
        code, message = _error_message(response)
        if status in (401, 403):
            logger.error("Stakaba %s %s: %s %s %s (check STAKABA_API_KEY)", method, path, status, code, message)
            raise PaymentProviderUnavailable(f"Stakaba rejected our credentials ({status}).")
        if status in (400, 422) or (status == 502 and "not registered" in message.lower()):
            logger.info("Stakaba %s %s rejected: %s %s %s", method, path, status, code, message)
            raise PaymentRejected(message or "The payment request was rejected.", code=code, status=status)
        logger.warning("Stakaba %s %s error: %s %s %s", method, path, status, code, message)
        raise PaymentProviderUnavailable(f"Stakaba returned {status}.")

    def create_card_payment(self, reference, amount, name, phone, email):
        """Hosted card checkout. Returns {"checkout_url", "internal_reference"}."""
        body = {
            "grossAmount": float(Decimal(str(amount))),
            "currency": "TZS",
            "customerEmail": email,
            "customerName": name,
            "customerPhone": msisdn(phone),
            "metadata": {"orderId": reference},
        }
        data = self._request("POST", "/payments/card", json=body)
        url, ref = data.get("checkoutUrl"), data.get("internalReference")
        if not url or not ref:
            raise PaymentProviderUnavailable("Stakaba did not return a checkout URL.")
        return {"checkout_url": url, "internal_reference": ref}

    def create_collection(self, reference, amount, phone, network):
        """USSD push to the customer's phone. Returns {"internal_reference", "status"}."""
        if network not in NETWORKS:
            raise PaymentRejected(f"Unknown mobile money network {network!r}.", code="invalid_network")
        body = {
            "grossAmount": whole_tzs(amount),
            "currency": "TZS",
            "mobileNumber": msisdn(phone),
            "network": network,
            "metadata": {"orderId": reference},
        }
        data = self._request("POST", "/payments/collection", json=body)
        ref = data.get("internalReference")
        if not ref:
            raise PaymentProviderUnavailable("Stakaba did not return a reference.")
        return {"internal_reference": ref, "status": str(data.get("status") or "").upper()}

    def get_transaction(self, internal_reference):
        """Transaction lookup. Bearer-only today (401 with an API key); kept for when Stakaba
        enables x-api-key here. Returns a normalised transaction, or None if Stakaba has none."""
        data = self._request("GET", f"/transactions/{internal_reference}", allow_404=True)
        return None if data is None else normalise_transaction(data)


def normalise_transaction(data):
    """Map a webhook body or transaction record to the fields our payment rules use."""
    data = data if isinstance(data, dict) else {}
    try:
        amount = Decimal(str(data.get("grossAmount")))
    except Exception:
        amount = None
    return {
        "internal_reference": str(data.get("internalReference") or ""),
        "status": str(data.get("status") or "").upper(),
        "amount": amount,
        "currency": str(data.get("currency") or "TZS").upper(),
        "network": str(data.get("network") or ""),
        "receipt": str(data.get("providerReference") or ""),
    }


def get_client():
    return StakabaClient()
