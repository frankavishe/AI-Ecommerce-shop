import pytest

from apps.orders.models import Order
from apps.payments import services
from apps.payments.models import Payment

pytestmark = pytest.mark.django_db

URL = "/api/payments/stakaba/webhook/hook-secret/"


@pytest.fixture
def payment(make_order, stakaba):
    payment, error = services.start_payment(make_order())
    assert error is None
    return payment


def post(client, body, url=URL):
    return client.post(url, body, format="json")


def reload(payment):
    payment.refresh_from_db()
    payment.order.refresh_from_db()
    return payment, payment.order


def test_success_webhook_marks_order_paid(api_client, payment, stakaba):
    res = post(api_client, stakaba.record(payment.provider_ref, 93000, order_id=payment.reference))
    assert res.status_code == 200 and res.data == {"received": True}

    payment, order = reload(payment)
    assert payment.status == Payment.Status.SUCCESS
    assert payment.collected_amount == 93000 and payment.channel == "TigoPesa"
    assert payment.receipt == f"MP{payment.provider_ref}"
    assert payment.raw_payload["webhook"]["stakabaFee"] == 125
    assert order.status == Order.Status.PAID and order.paid_at is not None
    assert order.events.filter(status="paid", source="provider").count() == 1


@pytest.mark.parametrize("url", [
    "/api/payments/stakaba/webhook/wrong/",
    "/api/payments/stakaba/webhook/",
])
def test_wrong_or_missing_token_is_404(api_client, payment, stakaba, url):
    res = post(api_client, stakaba.record(payment.provider_ref, 93000), url=url)
    assert res.status_code == 404
    payment, order = reload(payment)
    assert payment.status == Payment.Status.PENDING and "webhook" not in payment.raw_payload


def test_webhook_disabled_without_token(api_client, payment, stakaba, settings):
    settings.STAKABA_WEBHOOK_TOKEN = ""
    assert post(api_client, stakaba.record(payment.provider_ref, 93000)).status_code == 404


def test_failed_webhook_marks_attempt_failed_and_acknowledges(api_client, payment, stakaba):
    res = post(api_client, stakaba.record(payment.provider_ref, 93000, status="FAILED"))
    assert res.status_code == 200
    payment, order = reload(payment)
    assert payment.status == Payment.Status.FAILED and order.status == Order.Status.AWAITING_PAYMENT


def test_underpaid_webhook_is_a_mismatch(api_client, payment, stakaba):
    post(api_client, stakaba.record(payment.provider_ref, 1000))
    payment, order = reload(payment)
    assert payment.status == Payment.Status.MISMATCH and order.status == Order.Status.NEEDS_REVIEW


def test_unknown_reference_is_ignored(api_client, payment, stakaba):
    res = post(api_client, stakaba.record("STKMNOPE", 93000, order_id="NOSUCHREF"))
    assert res.status_code == 200
    payment, _ = reload(payment)
    assert payment.status == Payment.Status.PENDING


def test_falls_back_to_order_id_when_reference_was_never_saved(api_client, payment, stakaba):
    # The create call timed out, so we never stored Stakaba's internalReference.
    Payment.objects.filter(pk=payment.pk).update(provider_ref="")
    post(api_client, stakaba.record("STKMLATE", 93000, order_id=payment.reference))
    payment, order = reload(payment)
    assert payment.provider_ref == "STKMLATE" and payment.status == Payment.Status.SUCCESS


def test_order_id_cannot_hijack_another_transaction(api_client, payment, stakaba):
    post(api_client, stakaba.record("STKMOTHER", 93000, order_id=payment.reference))
    payment, _ = reload(payment)
    assert payment.status == Payment.Status.PENDING and payment.provider_ref == "STKM1"


def test_replayed_webhook_is_idempotent(api_client, payment, stakaba):
    for _ in range(5):
        assert post(api_client, stakaba.record(payment.provider_ref, 93000)).status_code == 200
    assert Payment.objects.filter(status=Payment.Status.SUCCESS).count() == 1
    assert payment.order.events.filter(status="paid").count() == 1


def test_with_api_confirmation_the_api_decides(api_client, payment, stakaba, settings):
    settings.STAKABA_CONFIRM_VIA_API = True
    # A forged body claims success, but Stakaba has no completed transaction.
    stakaba.pay(payment.provider_ref, 93000, status="PENDING")
    assert post(api_client, stakaba.record(payment.provider_ref, 93000)).status_code == 200
    payment, order = reload(payment)
    assert payment.status == Payment.Status.PENDING and order.status == Order.Status.AWAITING_PAYMENT

    stakaba.pay(payment.provider_ref, 93000)
    post(api_client, stakaba.record(payment.provider_ref, 93000))
    payment, order = reload(payment)
    assert order.status == Order.Status.PAID
