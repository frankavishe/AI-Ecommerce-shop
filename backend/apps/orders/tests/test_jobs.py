from datetime import timedelta

import pytest
from django.utils import timezone

from apps.orders.models import Order
from apps.orders.tasks import expire_unpaid_orders, send_payment_reminders
from apps.payments.models import Payment
from apps.payments.services import start_payment
from apps.payments.tasks import confirm_payment

pytestmark = pytest.mark.django_db


def age(order, minutes):
    placed = timezone.now() - timedelta(minutes=minutes)
    Order.objects.filter(pk=order.pk).update(placed_at=placed, expires_at=placed + timedelta(minutes=120))
    order.refresh_from_db()
    return order


def test_reminder_sent_once_after_30_minutes(make_order):
    due = age(make_order(), 31)
    fresh = age(make_order(), 10)
    paid = age(make_order(), 45)
    Order.objects.filter(pk=paid.pk).update(status=Order.Status.PAID)

    send_payment_reminders()
    send_payment_reminders()

    due.refresh_from_db()
    assert due.reminder_sent_at is not None
    assert due.events.filter(source="system", note__icontains="reminder").count() == 1
    for other in (fresh, paid):
        other.refresh_from_db()
        assert other.reminder_sent_at is None


def test_overdue_order_expires_and_returns_stock(make_order):
    order = age(make_order(stock=10, quantity=2), 121)
    keep = age(make_order(stock=10, quantity=2), 60)
    product = order.items.get().product

    expire_unpaid_orders()
    expire_unpaid_orders()

    order.refresh_from_db()
    keep.refresh_from_db()
    product.refresh_from_db()
    assert order.status == Order.Status.EXPIRED and order.stock_released
    assert order.events.filter(status="expired", source="system").count() == 1
    assert product.stock == 10
    assert keep.status == Order.Status.AWAITING_PAYMENT


def test_payment_after_expiry_needs_review(make_order, clickpesa):
    order = age(make_order(), 121)
    payment, _ = start_payment(order)
    expire_unpaid_orders()

    clickpesa.pay(payment.reference, 93000)
    confirm_payment(payment.id)

    payment.refresh_from_db()
    order.refresh_from_db()
    assert payment.status == Payment.Status.SUCCESS
    assert order.status == Order.Status.NEEDS_REVIEW and order.paid_at is None
    assert order.events.last().source == "provider"


def test_payment_after_cancellation_is_recorded_on_the_timeline(make_order, clickpesa):
    from apps.orders.services import transition

    order = make_order()
    payment, _ = start_payment(order)
    transition(order, Order.Status.CANCELLED, "admin")
    clickpesa.pay(payment.reference, 93000)
    confirm_payment(payment.id)

    order.refresh_from_db()
    assert order.status == Order.Status.CANCELLED
    assert "received while order was cancelled" in order.events.last().note
