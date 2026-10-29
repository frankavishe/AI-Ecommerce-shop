import pytest

from apps.orders.models import Order
from apps.payments import services
from apps.payments.clickpesa import checksum
from apps.payments.models import Payment

pytestmark = pytest.mark.django_db

URL = "/api/payments/clickpesa/webhook/"


@pytest.fixture
def payment(make_order, clickpesa):
    payment, error = services.start_payment(make_order())
    assert error is None
    return payment


def event(reference, status="SUCCESS", amount="93000", key=None, nested=False):
    data = {"orderReference": reference, "status": status, "collectedAmount": amount,
            "collectedCurrency": "TZS", "paymentReference": "PR1"}
    body = {"event": "PAYMENT RECEIVED", "data": data}
    if key and nested:
        data["checksum"] = checksum(data, key)
    elif key:
        body["checksum"] = checksum(body, key)
    return body


def post(client, body):
    return client.post(URL, body, format="json")


def test_valid_checksum_marks_order_paid(api_client, payment, clickpesa, settings):
    settings.CLICKPESA_CHECKSUM_KEY = "sig"
    clickpesa.pay(payment.reference, 93000)
    res = post(api_client, event(payment.reference, key="sig"))
    assert res.status_code == 200 and res.data == {"received": True}

    payment.refresh_from_db()
    order = payment.order
    order.refresh_from_db()
    assert payment.status == Payment.Status.SUCCESS
    assert payment.collected_amount == 93000 and payment.channel == "TIGO-PESA"
    assert payment.provider_ref == f"PR{payment.reference}"
    assert "webhook" in payment.raw_payload and "query" in payment.raw_payload
    assert order.status == Order.Status.PAID and order.paid_at is not None
    assert order.events.filter(status="paid", source="provider").count() == 1


def test_checksum_inside_data_is_accepted(api_client, payment, clickpesa, settings):
    settings.CLICKPESA_CHECKSUM_KEY = "sig"
    clickpesa.pay(payment.reference, 93000)
    res = post(api_client, event(payment.reference, key="sig", nested=True))
    assert res.status_code == 200
    payment.order.refresh_from_db()
    assert payment.order.status == Order.Status.PAID


@pytest.mark.parametrize("tamper", ["wrong", "missing"])
def test_bad_checksum_rejected(api_client, payment, clickpesa, settings, tamper):
    settings.CLICKPESA_CHECKSUM_KEY = "sig"
    clickpesa.pay(payment.reference, 93000)
    body = event(payment.reference, key="sig")
    if tamper == "wrong":
        body["data"]["collectedAmount"] = "1"
    else:
        del body["checksum"]
    res = post(api_client, body)
    assert res.status_code == 400

    payment.refresh_from_db()
    assert payment.status == Payment.Status.PENDING and "webhook" not in payment.raw_payload
    assert not clickpesa.requests_to(f"/payments/{payment.reference}")
    payment.order.refresh_from_db()
    assert payment.order.status == Order.Status.AWAITING_PAYMENT


def test_unknown_reference_is_ignored(api_client, payment, clickpesa):
    res = post(api_client, event("NOSUCHREF"))
    assert res.status_code == 200
    payment.refresh_from_db()
    assert payment.status == Payment.Status.PENDING


def test_replayed_webhook_is_idempotent(api_client, payment, clickpesa):
    clickpesa.pay(payment.reference, 93000)
    for _ in range(5):
        assert post(api_client, event(payment.reference)).status_code == 200
    assert Payment.objects.filter(status=Payment.Status.SUCCESS).count() == 1
    assert payment.order.events.filter(status="paid").count() == 1


def test_without_checksum_key_the_query_decides(api_client, payment, clickpesa):
    # A forged body claims success, but ClickPesa reports the payment still processing.
    clickpesa.pay(payment.reference, 93000, status="PROCESSING")
    assert post(api_client, event(payment.reference)).status_code == 200
    payment.refresh_from_db()
    assert payment.status == Payment.Status.PENDING
    payment.order.refresh_from_db()
    assert payment.order.status == Order.Status.AWAITING_PAYMENT

    clickpesa.pay(payment.reference, 93000)
    post(api_client, event(payment.reference))
    payment.order.refresh_from_db()
    assert payment.order.status == Order.Status.PAID
