from decimal import Decimal

import pytest
from django.db import transaction

from apps.orders.models import Order
from apps.payments import services
from apps.payments.models import Payment
from apps.payments.stakaba import normalise_transaction
from apps.payments.tasks import confirm_payment

pytestmark = pytest.mark.django_db


@pytest.fixture
def payment(make_order, stakaba):
    payment, error = services.start_payment(make_order())
    assert error is None
    return payment


def reload(payment):
    payment.refresh_from_db()
    payment.order.refresh_from_db()
    return payment, payment.order


def apply(payment, stakaba, amount, **kwargs):
    with transaction.atomic():
        locked = Payment.objects.select_for_update().get(pk=payment.pk)
        services.apply_provider_status(
            locked, normalise_transaction(stakaba.record(payment.provider_ref, amount, **kwargs))
        )
    return reload(payment)


def test_mobile_money_start_sends_prompt_and_stays_pending(payment, stakaba):
    payment, order = reload(payment)
    assert payment.method == "mobile_money" and payment.channel == "TigoPesa"
    assert payment.provider_ref == "STKM1" and payment.checkout_link == ""
    assert payment.status == Payment.Status.PENDING and order.status == Order.Status.AWAITING_PAYMENT


def test_collection_answering_success_marks_paid(make_order, stakaba):
    stakaba.collection_status = "SUCCESS"  # what the sandbox does
    payment, error = services.start_payment(make_order())
    assert error is None
    payment, order = reload(payment)
    assert payment.status == Payment.Status.SUCCESS and payment.collected_amount == 93000
    assert order.status == Order.Status.PAID and order.paid_at is not None


def test_collection_answering_failed_returns_an_error(make_order, stakaba):
    stakaba.collection_status = "FAILED"
    order = make_order()
    payment, error = services.start_payment(order)
    assert payment is None and error.code == "payment_failed"
    assert order.payments.get().status == Payment.Status.FAILED
    order.refresh_from_db()
    assert order.status == Order.Status.AWAITING_PAYMENT


def test_card_start(make_order, stakaba):
    order = make_order()
    payment, error = services.start_payment(order, method="card", email="amina@example.com")
    assert error is None
    assert payment.checkout_link == f"https://pay.test/{order.number}P1" and payment.provider_ref == "STKC1"
    order.refresh_from_db()
    assert order.contact_email == "amina@example.com"


def test_card_without_email_is_refused_before_calling(make_order, stakaba):
    payment, error = services.start_payment(make_order(), method="card")
    assert payment is None and error.code == "payment_rejected"
    assert not stakaba.calls and not Payment.objects.exists()


def test_mobile_money_below_minimum_is_refused(make_order, stakaba):
    order = make_order(quantity=1, price=100)
    order.total = Decimal("400")
    order.save()
    payment, error = services.start_payment(order)
    assert payment is None and "500" in error.message and not stakaba.calls


def test_fractional_total_is_refused_for_mobile_money(make_order, stakaba):
    order = make_order()
    order.total = Decimal("93000.50")
    order.save()
    _, error = services.start_payment(order)
    assert error.code == "payment_rejected" and not stakaba.calls


def test_unknown_network_prefix_asks_for_network(make_order, stakaba):
    order = make_order(phone="+255222000000")
    _, error = services.start_payment(order)
    assert error.code == "payment_rejected" and "network" in error.message
    payment, error = services.start_payment(order, network="Mpesa")
    assert error is None and payment.channel == "Mpesa"


def test_rejected_number_gives_customer_message(make_order, stakaba):
    stakaba.error = (502, {"error": "PROVIDER_ERROR",
                           "message": "The recipient number is not registered for mobile money on this network."})
    order = make_order()
    payment, error = services.start_payment(order)
    assert payment is None and error.code == "payment_rejected" and "not registered" in error.message
    assert order.payments.get().status == Payment.Status.FAILED


def test_provider_down_is_unavailable(make_order, stakaba):
    stakaba.down = True
    order = make_order()
    payment, error = services.start_payment(order)
    assert payment is None and error.code == "payment_unavailable"
    assert order.payments.get().status == Payment.Status.FAILED


def test_next_attempt_gets_a_new_reference(make_order, stakaba):
    order = make_order()
    stakaba.down = True
    services.start_payment(order)
    stakaba.down = False
    payment, _ = services.start_payment(order)
    assert payment.reference == f"{order.number}P2"


def test_amount_below_total_is_a_mismatch(payment, stakaba):
    payment, order = apply(payment, stakaba, 50000)
    assert payment.status == Payment.Status.MISMATCH and payment.collected_amount == 50000
    assert order.status == Order.Status.NEEDS_REVIEW and order.paid_at is None


def test_wrong_currency_is_not_paid(payment, stakaba):
    payment, order = apply(payment, stakaba, 93000, currency="USD")
    assert payment.status == Payment.Status.PENDING
    assert order.status == Order.Status.AWAITING_PAYMENT


def test_failed_payment_keeps_order_awaiting(payment, stakaba):
    payment, order = apply(payment, stakaba, 93000, status="FAILED")
    assert payment.status == Payment.Status.FAILED
    assert order.status == Order.Status.AWAITING_PAYMENT


def test_failed_payment_can_still_succeed_later(payment, stakaba):
    apply(payment, stakaba, 93000, status="FAILED")
    payment, order = apply(payment, stakaba, 93000)
    assert payment.status == Payment.Status.SUCCESS and order.status == Order.Status.PAID
    assert payment.receipt == f"MP{payment.provider_ref}"


def test_pending_changes_nothing(payment, stakaba):
    payment, order = apply(payment, stakaba, 93000, status="PENDING")
    assert payment.status == Payment.Status.PENDING
    assert order.status == Order.Status.AWAITING_PAYMENT
    assert order.events.count() == 1


def test_success_is_final(payment, stakaba):
    apply(payment, stakaba, 93000)
    payment, order = apply(payment, stakaba, 93000, status="FAILED")
    assert payment.status == Payment.Status.SUCCESS and order.status == Order.Status.PAID
    assert order.events.filter(status="paid").count() == 1


# --- confirm_payment task (only used with STAKABA_CONFIRM_VIA_API) ------------------------------


def test_confirm_task_applies_the_api_status(payment, stakaba):
    stakaba.pay(payment.provider_ref, 93000)
    confirm_payment(payment.id)
    payment, order = reload(payment)
    assert payment.status == Payment.Status.SUCCESS and order.status == Order.Status.PAID
    assert payment.raw_payload["query"]["amount"] == "93000"


def test_confirm_task_unknown_transaction_stays_pending(payment, stakaba):
    confirm_payment(payment.id)
    payment, _ = reload(payment)
    assert payment.status == Payment.Status.PENDING


def test_provider_down_leaves_payment_pending(payment, stakaba):
    stakaba.down = True
    confirm_payment.apply(args=[payment.id])  # retries are scheduled, nothing raises here
    payment, _ = reload(payment)
    assert payment.status == Payment.Status.PENDING
