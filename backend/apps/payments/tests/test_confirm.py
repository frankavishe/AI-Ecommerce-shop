import pytest

from apps.orders.models import Order
from apps.payments import services
from apps.payments.models import Payment
from apps.payments.tasks import confirm_payment

pytestmark = pytest.mark.django_db


@pytest.fixture
def payment(make_order, clickpesa):
    payment, _ = services.start_payment(make_order())
    return payment


def reload(payment):
    payment.refresh_from_db()
    payment.order.refresh_from_db()
    return payment, payment.order


def test_amount_below_total_is_a_mismatch(payment, clickpesa):
    clickpesa.pay(payment.reference, 50000)
    confirm_payment(payment.id)
    payment, order = reload(payment)
    assert payment.status == Payment.Status.MISMATCH and payment.collected_amount == 50000
    assert order.status == Order.Status.NEEDS_REVIEW and order.paid_at is None


def test_wrong_currency_is_not_paid(payment, clickpesa):
    clickpesa.pay(payment.reference, 93000, currency="USD")
    confirm_payment(payment.id)
    payment, order = reload(payment)
    assert payment.status == Payment.Status.PENDING
    assert order.status == Order.Status.AWAITING_PAYMENT


def test_failed_payment_keeps_order_awaiting(payment, clickpesa):
    clickpesa.pay(payment.reference, 93000, status="FAILED")
    confirm_payment(payment.id)
    payment, order = reload(payment)
    assert payment.status == Payment.Status.FAILED
    assert order.status == Order.Status.AWAITING_PAYMENT


def test_failed_payment_can_still_succeed_later(payment, clickpesa):
    clickpesa.pay(payment.reference, 93000, status="FAILED")
    confirm_payment(payment.id)
    clickpesa.pay(payment.reference, 93000, status="SETTLED")
    confirm_payment(payment.id)
    payment, order = reload(payment)
    assert payment.status == Payment.Status.SUCCESS and order.status == Order.Status.PAID


def test_processing_changes_nothing(payment, clickpesa):
    clickpesa.pay(payment.reference, 93000, status="PROCESSING")
    confirm_payment(payment.id)
    payment, order = reload(payment)
    assert payment.status == Payment.Status.PENDING
    assert order.status == Order.Status.AWAITING_PAYMENT
    assert order.events.count() == 1


def test_success_is_final(payment, clickpesa):
    clickpesa.pay(payment.reference, 93000)
    confirm_payment(payment.id)
    clickpesa.pay(payment.reference, 93000, status="FAILED")
    confirm_payment(payment.id)
    payment, order = reload(payment)
    assert payment.status == Payment.Status.SUCCESS and order.status == Order.Status.PAID


def test_provider_down_leaves_payment_pending(payment, clickpesa):
    clickpesa.down = True
    confirm_payment.apply(args=[payment.id])  # retries are scheduled, nothing raises here
    payment, order = reload(payment)
    assert payment.status == Payment.Status.PENDING
