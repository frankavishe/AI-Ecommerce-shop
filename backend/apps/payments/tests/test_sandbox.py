"""Live tests against the Stakaba sandbox. Opt-in: `pytest -m sandbox`.

They read STAKABA_API_KEY from the repo's .env and refuse to run with anything but a sandbox
(`sk_test_`) key, so no real money can move. Sandbox rules (stakaba.md): any valid number
succeeds, 255000000001 fails.
"""

from decimal import Decimal
from pathlib import Path

import pytest

from apps.orders.models import Order
from apps.payments import services
from apps.payments.models import Payment
from apps.payments.stakaba import PaymentProviderUnavailable, PaymentRejected, StakabaClient

pytestmark = pytest.mark.sandbox

ENV_FILE = Path(__file__).resolve().parents[4] / ".env"
FAIL_NUMBER = "+255000000001"


def _env(name):
    if not ENV_FILE.exists():
        return ""
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{name}="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


@pytest.fixture
def sandbox(settings):
    key = _env("STAKABA_API_KEY")
    if not key.startswith("sk_test_"):
        pytest.skip("STAKABA_API_KEY in .env is not a sandbox (sk_test_) key")
    settings.STAKABA_API_KEY = key
    settings.STAKABA_BASE_URL = _env("STAKABA_BASE_URL") or "https://api.stakaba.com"
    return StakabaClient(timeout=30.0)


def test_collection_success(sandbox):
    result = sandbox.create_collection("SBXTEST1", Decimal("1000"), "+255712345678", "TigoPesa")
    assert result["internal_reference"].startswith("STK")
    assert result["status"] == "SUCCESS"


def test_collection_failure_number(sandbox):
    result = sandbox.create_collection("SBXTEST2", Decimal("1000"), FAIL_NUMBER, "Mpesa")
    assert result["status"] == "FAILED"


def test_card_payment_returns_checkout_url(sandbox):
    result = sandbox.create_card_payment("SBXTEST3", Decimal("1500"), "Sandbox Test", "+255712345678", "sandbox@example.com")
    assert result["checkout_url"].startswith("https://")
    assert result["internal_reference"].startswith("STK")


def test_invalid_network_is_rejected_by_stakaba(sandbox):
    # Bypass our own check to confirm Stakaba's 422 maps to PaymentRejected.
    with pytest.raises(PaymentRejected) as info:
        sandbox._request("POST", "/payments/collection", json={
            "grossAmount": 1000, "mobileNumber": "255712345678", "network": "mpesa",
        })
    assert info.value.status == 422 and "network" in info.value.message


def test_fractional_amount_is_rejected_by_stakaba(sandbox):
    with pytest.raises(PaymentRejected) as info:
        sandbox._request("POST", "/payments/collection", json={
            "grossAmount": 999.5, "mobileNumber": "255712345678", "network": "Mpesa",
        })
    assert info.value.status in (400, 422)


def test_bad_key_is_unavailable(sandbox, settings):
    settings.STAKABA_API_KEY = "sk_test_definitely_wrong"
    with pytest.raises(PaymentProviderUnavailable):
        StakabaClient(timeout=30.0).create_collection("SBXTEST4", 1000, "+255712345678", "Mpesa")


def test_transaction_lookup_still_needs_bearer(sandbox):
    """Canary: when this starts failing, Stakaba accepts x-api-key on GET /transactions/{ref}.
    Then turn on STAKABA_CONFIRM_VIA_API (stakaba.md "Webhook trust")."""
    ref = sandbox.create_collection("SBXTEST5", 1000, "+255712345678", "Mpesa")["internal_reference"]
    with pytest.raises(PaymentProviderUnavailable, match="credentials"):
        sandbox.get_transaction(ref)


# --- End to end through our payment rules ---------------------------------------------------


@pytest.mark.django_db
def test_mobile_money_checkout_marks_order_paid(sandbox, make_order):
    order = make_order()  # 93,000 TZS to +255712345678 (TigoPesa)
    payment, error = services.start_payment(order)
    assert error is None, error
    payment.refresh_from_db()
    order.refresh_from_db()
    assert payment.provider_ref.startswith("STK") and payment.status == Payment.Status.SUCCESS
    assert payment.collected_amount == order.total
    assert order.status == Order.Status.PAID


@pytest.mark.django_db
def test_mobile_money_failure_keeps_order_awaiting(sandbox, make_order):
    order = make_order(phone=FAIL_NUMBER)
    payment, error = services.start_payment(order, network="Mpesa")
    assert payment is None and error.code == "payment_failed"
    order.refresh_from_db()
    assert order.status == Order.Status.AWAITING_PAYMENT
    assert order.payments.get().status == Payment.Status.FAILED


@pytest.mark.django_db
def test_card_checkout_gives_link(sandbox, make_order):
    order = make_order()
    payment, error = services.start_payment(order, method="card", email="sandbox@example.com")
    assert error is None, error
    assert payment.checkout_link.startswith("https://") and payment.provider_ref.startswith("STK")
    assert payment.status == Payment.Status.PENDING  # card is confirmed by the webhook
