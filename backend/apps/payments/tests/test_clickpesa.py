import hashlib
import hmac
import json
from decimal import Decimal

import pytest

from apps.payments import clickpesa as clickpesa_module
from apps.payments.clickpesa import (
    ClickPesaClient,
    PaymentProviderUnavailable,
    checksum,
    verify_checksum,
)


def test_checksum_matches_known_vector():
    payload = {"b": 1, "a": {"d": [{"y": 2, "x": 1}], "c": "x"}, "checksum": "old", "checksumMethod": "x"}
    canonical = '{"a":{"c":"x","d":[{"x":1,"y":2}]},"b":1}'
    expected = hmac.new(b"secret", canonical.encode(), hashlib.sha256).hexdigest()
    assert checksum(payload, "secret") == expected
    assert verify_checksum(payload, expected.upper(), "secret")
    assert not verify_checksum(payload, "0" * 64, "secret")
    assert not verify_checksum(payload, None, "secret")


def test_token_is_minted_once_and_reused(clickpesa):
    client = clickpesa_client()
    client.query_payments("ABC")
    client.query_payments("ABC")
    clickpesa_client().query_payments("ABC")
    assert len(clickpesa.requests_to("/generate-token")) == 1
    token_request = clickpesa.requests_to("/generate-token")[0]
    assert token_request.headers["client-id"] == "cid"
    assert token_request.headers["api-key"] == "key"
    assert clickpesa.requests_to("/payments/ABC")[0].headers["Authorization"] == "Bearer test-token"


def test_checkout_link_request_body(clickpesa):
    link = clickpesa_client().create_checkout_link(
        "K7Q2M9XDP1", Decimal("93000.00"), "Amina", "+255712345678", "Order K7Q2M9XD"
    )
    assert link == "https://pay.test/K7Q2M9XDP1"
    body = json.loads(clickpesa.requests_to("/generate-checkout-url")[0].content)
    assert body == {
        "totalPrice": "93000",
        "orderReference": "K7Q2M9XDP1",
        "orderCurrency": "TZS",
        "customerName": "Amina",
        "customerPhone": "255712345678",
        "description": "Order K7Q2M9XD",
    }


def test_checkout_link_is_signed_when_checksum_key_set(clickpesa, settings):
    settings.CLICKPESA_CHECKSUM_KEY = "sig"
    clickpesa_client().create_checkout_link("R1", Decimal("500"), "A", "+255712345678", "d")
    body = json.loads(clickpesa.requests_to("/generate-checkout-url")[0].content)
    assert body["checksum"] == checksum(body, "sig")


def test_network_error_raises_unavailable(clickpesa):
    clickpesa.down = True
    with pytest.raises(PaymentProviderUnavailable):
        clickpesa_client().query_payments("ABC")


def test_unconfigured_client_raises_unavailable():
    with pytest.raises(PaymentProviderUnavailable):
        ClickPesaClient().create_checkout_link("R1", Decimal("1"), "A", "+255712345678", "d")


def clickpesa_client():
    return clickpesa_module.get_client()
