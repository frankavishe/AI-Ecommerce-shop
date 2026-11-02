from decimal import Decimal

import httpx
import pytest

from apps.payments import stakaba as stakaba_module
from apps.payments.stakaba import (
    PaymentProviderUnavailable,
    PaymentRejected,
    StakabaClient,
    guess_network,
    msisdn,
    whole_tzs,
)


def client():
    return stakaba_module.get_client()


@pytest.mark.parametrize("raw", ["+255712345678", "0712 345 678", "255712345678", "712345678"])
def test_msisdn(raw):
    assert msisdn(raw) == "255712345678"


@pytest.mark.parametrize("phone,network", [
    ("+255742000331", "Mpesa"), ("+255754000000", "Mpesa"), ("+255682000000", "AirtelMoney"),
    ("+255712345678", "TigoPesa"), ("+255652000000", "TigoPesa"), ("+255622000000", "HaloPesa"),
    ("+255222000000", None),
])
def test_guess_network(phone, network):
    assert guess_network(phone) == network


def test_whole_tzs():
    assert whole_tzs(Decimal("5000.00")) == 5000
    with pytest.raises(PaymentRejected):
        whole_tzs(Decimal("4999.50"))


def test_collection_request(stakaba):
    result = client().create_collection("ORD1P1", Decimal("93000.00"), "+255712345678", "TigoPesa")
    assert result == {"internal_reference": "STKM1", "status": "PENDING"}
    request = stakaba.requests_to("/api/v1/payments/collection")[0]
    assert request.headers["x-api-key"] == "sk_test_fake"
    assert request.headers["accept"] == "application/json"
    assert "authorization" not in request.headers
    assert stakaba.bodies("/payments/collection")[0] == {
        "grossAmount": 93000, "currency": "TZS", "mobileNumber": "255712345678",
        "network": "TigoPesa", "metadata": {"orderId": "ORD1P1"},
    }


def test_collection_refuses_bad_network_and_fractions_without_calling(stakaba):
    with pytest.raises(PaymentRejected):
        client().create_collection("R", Decimal("1000"), "+255712345678", "mpesa")
    with pytest.raises(PaymentRejected):
        client().create_collection("R", Decimal("999.50"), "+255712345678", "Mpesa")
    assert not stakaba.calls


def test_card_request(stakaba):
    result = client().create_card_payment("ORD1P1", Decimal("93000"), "Amina", "+255712345678", "a@x.tz")
    assert result == {"checkout_url": "https://pay.test/ORD1P1", "internal_reference": "STKC1"}
    body = stakaba.bodies("/payments/card")[0]
    assert body["grossAmount"] == 93000 and body["customerEmail"] == "a@x.tz"
    assert body["customerPhone"] == "255712345678" and body["metadata"] == {"orderId": "ORD1P1"}


def test_2xx_without_reference_is_an_error(settings):
    settings.STAKABA_API_KEY = "sk_test_x"
    transport = httpx.MockTransport(lambda r: httpx.Response(201, json={}))
    with pytest.raises(PaymentProviderUnavailable):
        StakabaClient(transport=transport).create_collection("R", 1000, "+255712345678", "Mpesa")


@pytest.mark.parametrize("status,body,exc", [
    (422, {"detail": [{"loc": ["body", "network"], "msg": "Input should be 'Mpesa'", "type": "literal_error"}]},
     PaymentRejected),
    (400, {"error": "VALIDATION_ERROR", "message": "grossAmount must be positive", "details": {}}, PaymentRejected),
    (502, {"error": "PROVIDER_ERROR", "message": "The recipient number is not registered for mobile money on this network."},
     PaymentRejected),
    (502, {"error": "PROVIDER_ERROR", "message": "Payouts are temporarily unavailable."}, PaymentProviderUnavailable),
    (401, {"error": "UNAUTHORIZED", "message": "Invalid merchant API key"}, PaymentProviderUnavailable),
    (429, {"error": "RATE_LIMITED", "message": "slow down"}, PaymentProviderUnavailable),
    (500, {"error": "APP_ERROR", "message": "boom"}, PaymentProviderUnavailable),
])
def test_error_mapping(stakaba, status, body, exc):
    stakaba.error = (status, body)
    with pytest.raises(exc):
        client().create_collection("R", 1000, "+255712345678", "Mpesa")


def test_validation_error_message_from_fastapi_detail(stakaba):
    stakaba.error = (422, {"detail": [{"loc": ["body", "network"], "msg": "bad network"}]})
    with pytest.raises(PaymentRejected) as info:
        client().create_collection("R", 1000, "+255712345678", "Mpesa")
    assert info.value.message == "network: bad network" and info.value.status == 422


def test_network_error_raises_unavailable(stakaba):
    stakaba.down = True
    with pytest.raises(PaymentProviderUnavailable):
        client().create_collection("R", 1000, "+255712345678", "Mpesa")


def test_unconfigured_client_raises_unavailable():
    with pytest.raises(PaymentProviderUnavailable):
        StakabaClient().create_card_payment("R", 1, "A", "+255712345678", "a@x.tz")


def test_get_transaction(stakaba):
    assert client().get_transaction("STKM9") is None
    stakaba.pay("STKM9", 93000)
    tx = client().get_transaction("STKM9")
    assert tx["status"] == "SUCCESS" and tx["amount"] == Decimal("93000")
    assert tx["receipt"] == "MPSTKM9" and tx["network"] == "TigoPesa"


def test_base_url_gets_api_prefix(settings):
    settings.STAKABA_BASE_URL = "https://api.stakaba.com/"
    assert StakabaClient().base_url == "https://api.stakaba.com/api/v1"
    settings.STAKABA_BASE_URL = "https://api.stakaba.com/api/v1"
    assert StakabaClient().base_url == "https://api.stakaba.com/api/v1"
